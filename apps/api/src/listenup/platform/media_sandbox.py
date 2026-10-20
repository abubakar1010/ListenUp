"""Linux process boundary for every media-pool job (Architecture 12.1, ADR 0049).

The supervisor owns the queue connection. Job code runs in a fresh session with
hard address-space/CPU limits and a wall deadline. Descendants cannot detach; the
supervisor kills the group and reaps its leader, while init reaps orphaned children.
"""

import asyncio
import contextlib
import ctypes
import ctypes.util
import json
import os
import resource
import signal
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from listenup.platform.jobs import JobDeps, PermanentError
from listenup.platform.log import current_request_id


class MediaJobRetryable(Exception):
    """The child encountered a transient error; retain ordinary job retries."""


class MediaProcessFailed(PermanentError):
    """The isolated job died or exceeded its resource budget."""


async def run_process(
    command: Sequence[str],
    payload: bytes,
    *,
    seconds: float,
    memory_mb: int,
    cpu_seconds: int,
    env: dict[str, str] | None = None,
) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "listenup.platform.media_sandbox",
        str(memory_mb),
        str(cpu_seconds),
        *command,
        stdin=asyncio.subprocess.PIPE,
        env=env,
        # Job output is content-free logs, never parsed as a result.
        start_new_session=True,
    )

    async def watch_budget() -> None:
        while process.returncode is None:
            rss, cpu = _group_usage(process.pid)
            if rss > memory_mb * 1024 * 1024:
                raise MediaProcessFailed("media job exceeded its aggregate memory limit")
            if cpu > cpu_seconds:
                raise MediaProcessFailed("media job exceeded its aggregate CPU limit")
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(watch_budget())
    communication = asyncio.create_task(process.communicate(payload))
    try:
        async with asyncio.timeout(seconds):
            done, _ = await asyncio.wait(
                (watcher, communication), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
            await communication
        if process.returncode == 75:
            raise MediaJobRetryable("media job encountered a transient error")
        if process.returncode == 65:
            raise PermanentError("media job refused its input")
        if process.returncode != 0:
            raise MediaProcessFailed("media job exited unsuccessfully or exceeded a resource limit")
    except TimeoutError as error:
        raise MediaProcessFailed("media job exceeded its wall time limit") from error
    finally:
        # Also kill children left behind by a successful or crashed leader.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        watcher.cancel()
        communication.cancel()
        await asyncio.gather(watcher, communication, return_exceptions=True)


def _group_usage(group: int) -> tuple[int, float]:
    rss = ticks = 0
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            # comm may contain spaces or parentheses. Fields after its final ')'
            # start with state (field 3); pgrp is field 5, RSS field 24.
            fields = path.read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group:
                rss += int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
                ticks += sum(int(fields[i]) for i in (11, 12, 13, 14))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return rss, ticks / os.sysconf("SC_CLK_TCK")


async def run_job(name: str, deps: JobDeps, args: dict[str, object], seconds: float) -> None:
    from listenup.platform.config import get_settings

    settings = get_settings()
    with tempfile.TemporaryDirectory(
        prefix="media-job-", dir=settings.media_scratch_dir
    ) as scratch:
        await run_process(
            [sys.executable, "-m", "listenup.platform.media_job"],
            json.dumps(
                {
                    "name": name,
                    "job_id": deps.job_id,
                    "attempt": deps.attempt,
                    "args": args,
                    "request_id": current_request_id(),
                }
            ).encode(),
            env={**os.environ, "TMPDIR": scratch, "LISTENUP_MEDIA_SCRATCH_DIR": scratch},
            seconds=seconds,
            memory_mb=settings.media_job_memory_mb,
            cpu_seconds=settings.media_job_cpu_seconds,
        )


def _deny_detach() -> None:
    """Descendants must stay in the session the supervisor can kill. Fail closed."""
    library = ctypes.util.find_library("seccomp")
    if library is None:
        raise RuntimeError("libseccomp is required for media job isolation")
    seccomp = ctypes.CDLL(library, use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("cannot allocate media seccomp filter")
    try:
        for syscall in (b"setsid", b"setpgid"):
            number = seccomp.seccomp_syscall_resolve_name(syscall)
            if number < 0 or seccomp.seccomp_rule_add(context, 0x00050001, number, 0) != 0:
                raise RuntimeError("cannot restrict media process detachment")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("cannot load media seccomp filter")
    finally:
        seccomp.seccomp_release(context)


def main() -> None:
    memory = int(sys.argv[1]) * 1024 * 1024
    cpu = int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    _deny_detach()
    os.execvp(sys.argv[3], sys.argv[3:])


if __name__ == "__main__":
    main()
