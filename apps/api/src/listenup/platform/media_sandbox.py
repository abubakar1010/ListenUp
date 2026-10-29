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
import time
from collections.abc import Sequence
from pathlib import Path

from listenup.platform.jobs import JobDeps, PermanentError
from listenup.platform.log import current_request_id
from listenup.platform.telemetry import TRACE_ARG, job_trace_args


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
    pass_fds: tuple[int, ...] = (),
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
        pass_fds=pass_fds,
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
        if process.returncode == 71:
            raise MediaProcessFailed("media job exceeded its aggregate CPU limit")
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
    from listenup.platform.scratch import directory

    settings = get_settings()
    with directory(settings.media_scratch_dir, prefix="media-job-") as scratch:
        child_env = {
            **os.environ,
            "TMPDIR": str(scratch),
            "LISTENUP_MEDIA_SCRATCH_DIR": str(scratch),
        }
        # Ordinary media children never inherit root-maintenance authority.
        child_env.pop("LISTENUP_SCRATCH_CLEANUP_ROOT", None)
        if name == "ops.sweep_scratch_files" and settings.media_scratch_dir is not None:
            child_env["LISTENUP_SCRATCH_CLEANUP_ROOT"] = settings.media_scratch_dir
        # Pass a shared lifetime lease through the launcher to the actual child.
        # It survives supervisor death and protects an orphan still using scratch.
        import fcntl

        from listenup.platform.scratch import MARKER

        with (scratch / MARKER).open("rb") as lease:
            fcntl.flock(lease, fcntl.LOCK_SH)
            await run_process(
                [sys.executable, "-m", "listenup.platform.media_job"],
                json.dumps(
                    {
                        "name": name,
                        "job_id": deps.job_id,
                        "attempt": deps.attempt,
                        "args": args,
                        "request_id": current_request_id(),
                        "trace": job_trace_args().get(TRACE_ARG),
                    }
                ).encode(),
                env=child_env,
                pass_fds=(lease.fileno(),),
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

    class Argument(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_uint),
            ("datum_a", ctypes.c_uint64),
            ("datum_b", ctypes.c_uint64),
        ]

    seccomp.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(Argument),
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
        # SIG_IGN/SA_NOCLDWAIT discard usage without wait4. Keep SIGCHLD at its
        # default disposition throughout the tree, so every exit remains waitable.
        number = seccomp.seccomp_syscall_resolve_name(b"rt_sigaction")
        comparison = Argument(0, 4, signal.SIGCHLD, 0)  # SCMP_CMP_EQ
        if (
            number < 0
            or seccomp.seccomp_rule_add_array(
                context, 0x00050001, number, 1, ctypes.byref(comparison)
            )
            != 0
        ):
            raise RuntimeError("cannot preserve media child accounting")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("cannot load media seccomp filter")
    finally:
        seccomp.seccomp_release(context)


def _reap_job(command: Sequence[str], cpu_seconds: int) -> int:
    """Retain orphaned-child CPU in this group's wait4 counters (ADR 0049).

    The launcher stays alive as a Linux subreaper. Reparented descendants are
    reaped here, rather than by the container init outside the monitored group.
    SIGCHLD auto-reaping is denied by the inherited seccomp filter.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError("cannot retain media descendant accounting")
    child = os.fork()
    if child == 0:
        try:
            os.execvp(command[0], list(command))
        except BaseException:
            os._exit(70)
    result: int | None = None
    while True:
        try:
            # __WALL includes clone children that request no SIGCHLD on exit.
            pid, status, _ = os.wait4(-1, os.WNOHANG | 0x40000000)
        except ChildProcessError:
            return result if result is not None else 70
        if pid == child:
            result = os.waitstatus_to_exitcode(status)
            if result < 0:
                result = 128 - result
        if _group_usage(os.getpgrp())[1] > cpu_seconds:
            result = 71
        if result is not None:
            # The workload has ended (or exceeded its budget). Stop leftover
            # descendants and keep reaping until their usage has been collected.
            for path in Path("/proc").glob("[0-9]*/stat"):
                try:
                    fields = path.read_text().rsplit(")", 1)[1].split()
                    identifier = int(path.parent.name)
                    if int(fields[2]) == os.getpgrp() and identifier != os.getpid():
                        os.kill(identifier, signal.SIGKILL)
                except (FileNotFoundError, ProcessLookupError):
                    continue
        if pid == 0:
            time.sleep(0.01)


def main() -> None:
    memory = int(sys.argv[1]) * 1024 * 1024
    cpu = int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    _deny_detach()
    raise SystemExit(_reap_job(sys.argv[3:], cpu))


if __name__ == "__main__":
    main()
