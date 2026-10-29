"""Owned scratch survives active work and is reclaimed after a killed owner."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from listenup.platform import scratch


def old(path: Path) -> None:
    then = time.time() - 7200
    for item in [*path.rglob("*"), path]:
        os.utime(item, (then, then), follow_symlinks=False)


def abandoned(root: Path) -> Path:
    # A real process dies without running its context manager's cleanup.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from listenup.platform.scratch import directory; import os,sys; "
            "c=directory(sys.argv[1], prefix='media-job-'); p=c.__enter__(); "
            "print(p,flush=True); os._exit(0)",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    path = Path(result.stdout.strip())
    old(path)
    return path


def test_sweep_removes_abandoned_owned_directory_only(tmp_path):
    stale = abandoned(tmp_path)
    foreign = tmp_path / "media-job-unrelated"
    foreign.mkdir()
    old(foreign)
    assert scratch.sweep(tmp_path, 3600) == 1
    assert not stale.exists()
    assert foreign.exists()


def test_sweep_keeps_active_directory_even_when_all_files_are_old(tmp_path):
    with scratch.directory(str(tmp_path), prefix="media-job-") as path:
        (path / "audio.wav").write_bytes(b"in use")
        old(path)
        assert scratch.sweep(tmp_path, 60) == 0
        assert (path / "audio.wav").read_bytes() == b"in use"
    assert not path.exists()


def test_sweep_keeps_recent_descendants(tmp_path):
    stale = abandoned(tmp_path)
    (stale / "recent").write_bytes(b"x")
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists()


def test_sweep_does_not_follow_entry_or_marker_symlinks(tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    (target / "keep").write_bytes(b"safe")
    stale = abandoned(tmp_path)
    for item in stale.iterdir():
        item.unlink()
    stale.rmdir()
    stale.symlink_to(target, target_is_directory=True)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert (target / "keep").read_bytes() == b"safe"


def test_overlapping_scratch_sweeps_remove_an_entry_once(tmp_path):
    stale = abandoned(tmp_path)

    async def go():
        return await asyncio.gather(
            asyncio.to_thread(scratch.sweep, tmp_path, 3600),
            asyncio.to_thread(scratch.sweep, tmp_path, 3600),
        )

    assert sum(asyncio.run(go())) == 1
    assert not stale.exists()


def test_media_supervisor_sweep_reaches_pool_root(tmp_path, monkeypatch):
    from listenup.ops import retention
    from listenup.platform import media_sandbox
    from listenup.platform.config import Settings
    from listenup.platform.jobs import JobDeps

    stale = abandoned(tmp_path)
    settings = Settings(media_scratch_dir=str(tmp_path))
    monkeypatch.setattr("listenup.platform.config.get_settings", lambda: settings)

    async def child(command, payload, *, env, **kwargs):
        monkeypatch.setattr(
            retention,
            "get_settings",
            lambda: Settings(
                media_scratch_dir=env["LISTENUP_MEDIA_SCRATCH_DIR"],
                scratch_cleanup_root=env.get("LISTENUP_SCRATCH_CLEANUP_ROOT"),
            ),
        )
        assert await retention.sweep_scratch_files(JobDeps(None, None, 1)) == 1

    monkeypatch.setattr(media_sandbox, "run_process", child)
    asyncio.run(media_sandbox.run_job("ops.sweep_scratch_files", JobDeps(None, 1, 1), {}, 600))
    assert not stale.exists()


def test_default_pool_sweeps_its_export_scratch(tmp_path, monkeypatch):
    from listenup.ops import retention
    from listenup.platform.config import Settings
    from listenup.platform.jobs import JobDeps

    stale = abandoned(tmp_path)
    monkeypatch.setattr(
        retention, "get_settings", lambda: Settings(media_scratch_dir=str(tmp_path))
    )
    assert asyncio.run(retention.sweep_default_scratch_files(JobDeps(None, None, 1))) == 1
    assert not stale.exists()


def test_invalid_marker_and_unmarked_entries_are_kept(tmp_path):
    stale = abandoned(tmp_path)
    (stale / scratch.MARKER).write_bytes(b"unrelated")
    old(stale)
    unmarked = stale.parent / "foreign"
    unmarked.mkdir()
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists() and unmarked.exists()


def test_fifo_marker_does_not_block_the_sweep(tmp_path):
    stale = abandoned(tmp_path)
    marker = stale / scratch.MARKER
    marker.unlink()
    os.mkfifo(marker)
    old(stale)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from listenup.platform.scratch import sweep; "
            "from pathlib import Path; import sys; assert sweep(Path(sys.argv[1]),3600)==0",
            str(tmp_path),
        ],
        check=True,
        timeout=2,
    )
    assert stale.exists()


def test_marker_symlink_is_never_followed(tmp_path):
    stale = abandoned(tmp_path)
    marker = stale / scratch.MARKER
    marker.unlink()
    target = tmp_path / "foreign-marker"
    target.write_bytes(scratch.MAGIC)
    marker.symlink_to(target)
    old(stale)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists() and target.read_bytes() == scratch.MAGIC


def test_unremovable_directory_does_not_block_other_entries(tmp_path, monkeypatch):
    blocked, other = abandoned(tmp_path), abandoned(tmp_path)
    original = scratch.shutil.rmtree

    def remove(path, **kwargs):
        if Path(path) == blocked:
            raise PermissionError("refused")
        return original(path, **kwargs)

    monkeypatch.setattr(scratch.shutil, "rmtree", remove)
    assert scratch.sweep(tmp_path, 3600) == 1
    assert blocked.exists() and not other.exists()


def test_namespace_symlink_is_refused_and_not_swept(tmp_path):
    target = tmp_path / "foreign"
    target.mkdir()
    (tmp_path / scratch.NAMESPACE).symlink_to(target, target_is_directory=True)
    assert scratch.sweep(tmp_path, 3600) == 0
    with (
        pytest.raises(OSError, match="symlink"),
        scratch.directory(str(tmp_path), prefix="media-job-"),
    ):
        pytest.fail("must not enter a foreign namespace")


def test_failed_work_removes_its_directory(tmp_path):
    with (
        pytest.raises(RuntimeError, match="failed"),
        scratch.directory(str(tmp_path), prefix="media-job-") as path,
    ):
        raise RuntimeError("failed")
    assert not path.exists()


def test_media_child_receives_a_lifetime_lease(tmp_path, monkeypatch):
    import fcntl

    from listenup.platform import media_sandbox
    from listenup.platform.config import Settings
    from listenup.platform.jobs import JobDeps

    monkeypatch.setattr(
        "listenup.platform.config.get_settings", lambda: Settings(media_scratch_dir=str(tmp_path))
    )

    async def child(command, payload, *, env, pass_fds, **kwargs):
        path = Path(env["LISTENUP_MEDIA_SCRATCH_DIR"])
        assert len(pass_fds) == 1
        assert os.fstat(pass_fds[0]).st_ino == (path / scratch.MARKER).stat().st_ino
        # Check in a separate process that the inherited lease remains held even
        # without any lock taken by the child application.
        code = (
            "import fcntl,os,sys; fcntl.flock(int(sys.argv[1]),fcntl.LOCK_SH); "
            "print('leased',flush=True); sys.stdin.read()"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(pass_fds[0])],
            pass_fds=pass_fds,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout.readline().strip() == "leased"
            with (path / scratch.MARKER).open("rb") as marker, pytest.raises(BlockingIOError):
                fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            process.communicate("", timeout=5)

    monkeypatch.setattr(media_sandbox, "run_process", child)
    asyncio.run(media_sandbox.run_job("content.convert_upload", JobDeps(None, 1, 1), {}, 600))
