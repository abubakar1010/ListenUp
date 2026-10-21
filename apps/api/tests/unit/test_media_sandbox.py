import sys
from pathlib import Path

import pytest

from listenup.platform import media_sandbox


@pytest.mark.anyio
@pytest.mark.parametrize(
    "script,seconds,memory,cpu",
    [
        ("import time; time.sleep(30)", 0.2, 128, 5),
        ("x = bytearray(512 * 1024 * 1024)", 5, 128, 5),
        ("while True: pass", 5, 128, 1),
    ],
)
async def test_sandbox_kills_jobs_over_time_memory_or_cpu(
    script: str,
    seconds: float,
    memory: int,
    cpu: int,
) -> None:
    with pytest.raises(media_sandbox.MediaProcessFailed):
        await media_sandbox.run_process(
            [sys.executable, "-c", script], b"", seconds=seconds, memory_mb=memory, cpu_seconds=cpu
        )


@pytest.mark.anyio
async def test_sandbox_allows_bounded_work() -> None:
    await media_sandbox.run_process(
        [sys.executable, "-c", "pass"], b"", seconds=5, memory_mb=128, cpu_seconds=2
    )


@pytest.mark.anyio
async def test_memory_budget_covers_descendants_together() -> None:
    script = """
import subprocess, sys, time
children = [subprocess.Popen([sys.executable, '-c',
    'import time; x=bytearray(80*1024*1024); time.sleep(30)']) for _ in range(2)]
time.sleep(30)
"""
    with pytest.raises(media_sandbox.MediaProcessFailed, match="memory"):
        await media_sandbox.run_process(
            [sys.executable, "-c", script], b"", seconds=5, memory_mb=128, cpu_seconds=5
        )


@pytest.mark.anyio
async def test_media_process_failure_settles_job_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from listenup.platform import jobs

    name = "test.media_limit"
    settle = AsyncMock()
    jobs.job(jobs.Lane.INTAKE, name, on_give_up=settle)(AsyncMock())
    database = object()
    monkeypatch.setattr(jobs._runtime, "isolate_media", True)
    monkeypatch.setattr(
        media_sandbox, "run_job", AsyncMock(side_effect=media_sandbox.MediaProcessFailed("limit"))
    )
    deps = jobs.JobDeps(database, 1, 1)
    try:
        with pytest.raises(jobs.PermanentError):
            await jobs.run_handler(name, deps, media_object_id="test")
        settle.assert_awaited_once_with(deps, media_object_id="test")
    finally:
        jobs._registry.pop(name)
        jobs.app.tasks.pop(name)


@pytest.mark.anyio
async def test_child_transient_errors_still_use_job_retries() -> None:
    from listenup.platform.jobs import PermanentError

    with pytest.raises(Exception) as raised:
        await media_sandbox.run_process(
            [sys.executable, "-c", "raise SystemExit(75)"],
            b"",
            seconds=5,
            memory_mb=128,
            cpu_seconds=2,
        )
    assert not isinstance(raised.value, PermanentError)


@pytest.mark.anyio
async def test_refused_input_keeps_permanent_error() -> None:
    from listenup.platform.jobs import PermanentError

    with pytest.raises(PermanentError, match="refused"):
        await media_sandbox.run_process(
            [sys.executable, "-c", "raise SystemExit(65)"],
            b"",
            seconds=5,
            memory_mb=128,
            cpu_seconds=2,
        )


@pytest.mark.anyio
async def test_sandbox_disallows_detaching_children() -> None:
    script = """
import os
for function in (os.setsid, lambda: os.setpgid(0, 0)):
    try:
        function()
    except PermissionError:
        pass
    else:
        raise AssertionError('child detached from supervisor')
"""
    await media_sandbox.run_process(
        [sys.executable, "-c", script], b"", seconds=5, memory_mb=128, cpu_seconds=2
    )


@pytest.mark.anyio
async def test_transient_child_failure_settles_only_after_last_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from listenup.platform import jobs

    name = "test.media_transient"
    settle = AsyncMock()
    jobs.job(jobs.Lane.INTAKE, name, max_attempts=2, on_give_up=settle)(AsyncMock())
    monkeypatch.setattr(jobs._runtime, "isolate_media", True)
    monkeypatch.setattr(
        media_sandbox,
        "run_job",
        AsyncMock(side_effect=media_sandbox.MediaJobRetryable("db offline")),
    )
    try:
        for attempt in (1, 2):
            deps = jobs.JobDeps(object(), 1, attempt)
            with pytest.raises(media_sandbox.MediaJobRetryable):
                await jobs.run_handler(name, deps)
            assert settle.await_count == (0 if attempt == 1 else 1)
    finally:
        jobs._registry.pop(name)
        jobs.app.tasks.pop(name)


def test_launcher_sets_hard_limits_before_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    limits = Mock()
    detach = Mock()
    execute = Mock()
    monkeypatch.setattr(media_sandbox.resource, "setrlimit", limits)
    monkeypatch.setattr(media_sandbox, "_deny_detach", detach)
    execute.return_value = 0
    monkeypatch.setattr(media_sandbox, "_reap_job", execute)
    monkeypatch.setattr(media_sandbox.sys, "argv", ["launcher", "128", "7", "python", "-c", "pass"])
    with pytest.raises(SystemExit) as exit_status:
        media_sandbox.main()
    assert exit_status.value.code == 0
    limits.assert_any_call(media_sandbox.resource.RLIMIT_AS, (128 * 1024**2,) * 2)
    limits.assert_any_call(media_sandbox.resource.RLIMIT_CPU, (7, 7))
    limits.assert_any_call(media_sandbox.resource.RLIMIT_CORE, (0, 0))
    detach.assert_called_once()
    execute.assert_called_once_with(["python", "-c", "pass"], 7)


@pytest.mark.parametrize(
    "failure", ["library", "allocation", "syscall", "rule", "accounting", "load", None]
)
def test_detachment_filter_fails_closed(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    from unittest.mock import MagicMock

    library = MagicMock()
    library.seccomp_init.return_value = None if failure == "allocation" else 123
    library.seccomp_syscall_resolve_name.return_value = -1 if failure == "syscall" else 12
    library.seccomp_rule_add.return_value = -1 if failure == "rule" else 0
    library.seccomp_rule_add_array.return_value = -1 if failure == "accounting" else 0
    library.seccomp_load.return_value = -1 if failure == "load" else 0
    monkeypatch.setattr(
        media_sandbox.ctypes.util,
        "find_library",
        lambda _: None if failure == "library" else "libseccomp.so",
    )
    monkeypatch.setattr(media_sandbox.ctypes, "CDLL", lambda *a, **k: library)
    if failure is not None:
        with pytest.raises(RuntimeError):
            media_sandbox._deny_detach()
    else:
        media_sandbox._deny_detach()
        assert library.seccomp_rule_add.call_count == 2
        library.seccomp_load.assert_called_once_with(123)
    if failure not in ("library", "allocation"):
        library.seccomp_release.assert_called_once_with(123)


@pytest.mark.anyio
async def test_job_scratch_is_removed_after_a_killed_job(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from listenup.platform import config
    from listenup.platform.jobs import JobDeps

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            media_scratch_dir=str(tmp_path), media_job_memory_mb=128, media_job_cpu_seconds=2
        ),
    )

    async def killed(command, payload, **kwargs):
        from pathlib import Path

        directory = Path(kwargs["env"]["LISTENUP_MEDIA_SCRATCH_DIR"])
        assert directory.is_relative_to(tmp_path)
        (directory / "partial-conversion").write_text("left behind by SIGKILL")
        raise media_sandbox.MediaProcessFailed("limit")

    monkeypatch.setattr(media_sandbox, "run_process", killed)
    with pytest.raises(media_sandbox.MediaProcessFailed):
        await media_sandbox.run_job("any.future.media.job", JobDeps(object(), 1, 1), {}, 3)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_cpu_budget_covers_descendants_together() -> None:
    script = """
import subprocess, sys, time
children = [subprocess.Popen([sys.executable, '-c', 'while True: pass']) for _ in range(2)]
time.sleep(30)
"""
    with pytest.raises(media_sandbox.MediaProcessFailed, match="aggregate CPU"):
        await media_sandbox.run_process(
            [sys.executable, "-c", script], b"", seconds=10, memory_mb=128, cpu_seconds=1
        )


@pytest.mark.anyio
@pytest.mark.parametrize("orphan", [False, True])
async def test_cpu_budget_retains_auto_reaped_and_orphaned_children(orphan: bool) -> None:
    # Each child stays below RLIMIT_CPU. Ignoring SIGCHLD used to discard its
    # usage; double-forking also discarded usage when the container init reaped it.
    script = f"""
import os, signal, time
try:
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
except PermissionError:
    pass  # a fail-closed sandbox may prohibit disabling child accounting
for _ in range(8):
    if os.fork() == 0:
        if {orphan!r} and os.fork() != 0:
            os._exit(0)
        start = time.process_time()
        while time.process_time() - start < .3:
            pass
        os._exit(0)
    time.sleep(.5)
"""
    with pytest.raises(media_sandbox.MediaProcessFailed, match="CPU"):
        await media_sandbox.run_process(
            [sys.executable, "-c", script], b"", seconds=15, memory_mb=128, cpu_seconds=1
        )


@pytest.mark.anyio
async def test_cancellation_kills_descendants(tmp_path) -> None:
    import asyncio

    marker = tmp_path / "child-pid"
    script = f"""
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path({str(marker)!r}).write_text(str(child.pid))
time.sleep(30)
"""
    running = asyncio.create_task(
        media_sandbox.run_process(
            [sys.executable, "-c", script], b"", seconds=10, memory_mb=128, cpu_seconds=3
        )
    )
    async with asyncio.timeout(5):
        while not marker.exists():
            if running.done():
                await running
            await asyncio.sleep(0.01)

    child = int(marker.read_text())
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    async with asyncio.timeout(3):
        while (stat := Path(f"/proc/{child}/stat")).exists():
            if stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                break  # terminated, awaiting the container init's reap
            await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "status,over_budget,expected", [(0, False, 0), (15, False, 143), (0, True, 71)]
)
def test_reaper_preserves_result_and_settles_cpu_before_exit(
    monkeypatch, status, over_budget, expected
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    libc = SimpleNamespace(prctl=Mock(return_value=0))
    monkeypatch.setattr(media_sandbox.ctypes, "CDLL", lambda *a, **k: libc)
    monkeypatch.setattr(media_sandbox.os, "fork", lambda: 31)
    monkeypatch.setattr(
        media_sandbox.os,
        "wait4",
        Mock(side_effect=[(0, 0, None), (31, status, None), ChildProcessError()]),
    )
    monkeypatch.setattr(media_sandbox, "_group_usage", lambda group: (0, 2 if over_budget else 0))
    monkeypatch.setattr(media_sandbox.Path, "glob", lambda *a: [])
    monkeypatch.setattr(media_sandbox.time, "sleep", Mock())
    assert media_sandbox._reap_job(["python", "-c", "pass"], 1) == expected
    libc.prctl.assert_called_once_with(36, 1, 0, 0, 0)


def test_reaper_refuses_missing_kernel_support(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        media_sandbox.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: -1)
    )
    with pytest.raises(RuntimeError, match="accounting"):
        media_sandbox._reap_job(["unused"], 1)


def test_reaper_kills_leftovers_and_tolerates_disappearing_processes(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setattr(
        media_sandbox.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0)
    )
    monkeypatch.setattr(media_sandbox.os, "fork", lambda: 31)
    monkeypatch.setattr(
        media_sandbox.os, "wait4", Mock(side_effect=[(31, 0, None), ChildProcessError()])
    )
    monkeypatch.setattr(media_sandbox.os, "getpgrp", lambda: 123)
    monkeypatch.setattr(media_sandbox.os, "getpid", lambda: 99)
    monkeypatch.setattr(media_sandbox, "_group_usage", lambda group: (0, 0))
    paths = [
        SimpleNamespace(
            parent=SimpleNamespace(name="32"), read_text=lambda: "32 (leftover) S 0 123"
        ),
        SimpleNamespace(parent=SimpleNamespace(name="99"), read_text=lambda: "99 (reaper) S 0 123"),
    ]
    monkeypatch.setattr(media_sandbox.Path, "glob", lambda *a: paths)
    killed = Mock(side_effect=ProcessLookupError())
    monkeypatch.setattr(media_sandbox.os, "kill", killed)
    assert media_sandbox._reap_job(["unused"], 1) == 0
    killed.assert_called_once_with(32, media_sandbox.signal.SIGKILL)


def test_reaper_missing_executable_has_fixed_failure_code(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setattr(
        media_sandbox.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0)
    )
    monkeypatch.setattr(media_sandbox.os, "fork", lambda: 0)
    monkeypatch.setattr(media_sandbox.os, "execvp", Mock(side_effect=OSError("private input")))
    monkeypatch.setattr(media_sandbox.os, "_exit", Mock(side_effect=SystemExit(70)))
    with pytest.raises(SystemExit) as status:
        media_sandbox._reap_job(["missing"], 1)
    assert status.value.code == 70
