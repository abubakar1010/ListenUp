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
    original = scratch.os.rmdir

    def remove(path, **kwargs):
        if Path(path).name == blocked.name:
            raise PermissionError("refused")
        return original(path, **kwargs)

    monkeypatch.setattr(scratch.os, "rmdir", remove)
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


def test_lease_survives_the_real_media_launcher(tmp_path):
    import fcntl

    from listenup.platform.media_sandbox import run_process

    async def go():
        with (
            scratch.directory(str(tmp_path), prefix="media-job-") as path,
            (path / scratch.MARKER).open("rb") as lease,
        ):
            fcntl.flock(lease, fcntl.LOCK_SH)
            await run_process(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; "
                    "assert os.read(int(sys.argv[1]),100)==b'listenup-scratch-v1\\n'",
                    str(lease.fileno()),
                ],
                b"",
                seconds=20,
                memory_mb=512,
                cpu_seconds=10,
                pass_fds=(lease.fileno(),),
            )
        assert not path.exists()

    asyncio.run(go())


def test_directory_replaced_during_scan_is_not_deleted(tmp_path, monkeypatch):
    stale = abandoned(tmp_path)
    identity = stale.stat().st_ino
    replacement = tmp_path / "unmarked"
    replacement.mkdir()
    (replacement / "keep").write_bytes(b"unrelated")
    old(replacement)
    original = scratch._newest_mtime
    swapped = False

    def scan(descriptor):
        nonlocal swapped
        if not swapped and os.fstat(descriptor).st_ino == identity:
            swapped = True
            stale.rename(tmp_path / "original")
            replacement.rename(stale)
        return original(descriptor)

    monkeypatch.setattr(scratch, "_newest_mtime", scan)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert swapped
    assert (stale / "keep").read_bytes() == b"unrelated"


def test_marker_replaced_by_active_lease_during_scan_is_preserved(tmp_path, monkeypatch):
    import fcntl

    stale = abandoned(tmp_path)
    original = scratch._newest_mtime
    leases = []

    def scan(descriptor):
        if not leases:
            (stale / scratch.MARKER).rename(tmp_path / "original-marker")
            lease = (stale / scratch.MARKER).open("xb")
            lease.write(scratch.MAGIC)
            lease.flush()
            fcntl.flock(lease, fcntl.LOCK_SH)
            leases.append(lease)
            then = time.time() - 7200
            for item in (stale / scratch.MARKER, stale):
                os.utime(item, (then, then))
        return original(descriptor)

    monkeypatch.setattr(scratch, "_newest_mtime", scan)
    try:
        assert scratch.sweep(tmp_path, 3600) == 0
        assert (stale / scratch.MARKER).read_bytes() == scratch.MAGIC
    finally:
        for lease in leases:
            lease.close()


def test_nonprivate_namespace_is_refused_and_not_swept(tmp_path):
    stale = abandoned(tmp_path)
    stale.parent.chmod(0o777)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists()
    with (
        pytest.raises(OSError, match="private"),
        scratch.directory(str(tmp_path), prefix="media-job-"),
    ):
        pytest.fail("must not use a namespace writable by other users")


def test_replacement_after_validation_cannot_redirect_removal(tmp_path, monkeypatch):
    stale = abandoned(tmp_path)
    (stale / "data").write_bytes(b"expired")
    old(stale)
    inode = stale.stat().st_ino
    replacement = tmp_path / "unmarked"
    replacement.mkdir()
    (replacement / "data").write_bytes(b"keep")
    original = os.scandir
    swapped = False

    def scan(path):
        nonlocal swapped
        if isinstance(path, int) and not swapped and os.fstat(path).st_ino == inode:
            swapped = True
            stale.rename(tmp_path / "original")
            replacement.rename(stale)
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert swapped
    assert (stale / "data").read_bytes() == b"keep"


def test_stale_tree_removal_does_not_follow_nested_symlinks(tmp_path):
    stale = abandoned(tmp_path)
    nested = stale / "nested"
    nested.mkdir()
    (nested / "audio").write_bytes(b"expired")
    (stale / "file").write_bytes(b"expired")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep").write_bytes(b"safe")
    (stale / "link").symlink_to(foreign, target_is_directory=True)
    old(stale)
    assert scratch.sweep(tmp_path, 3600) == 1
    assert not stale.exists()
    assert (foreign / "keep").read_bytes() == b"safe"


def test_namespace_owned_by_another_user_is_refused(tmp_path, monkeypatch):
    stale = abandoned(tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: stale.stat().st_uid + 1)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists()
    with (
        pytest.raises(OSError, match="owned"),
        scratch.directory(str(tmp_path), prefix="media-job-"),
    ):
        pytest.fail("must not use another user's namespace")


@pytest.mark.parametrize("kind", ["directory", "hardlink", "writable", "foreign"])
def test_invalid_marker_ownership_is_preserved(tmp_path, monkeypatch, kind):
    stale = abandoned(tmp_path)
    marker = stale / scratch.MARKER
    if kind == "directory":
        marker.unlink()
        marker.mkdir()
    elif kind == "hardlink":
        os.link(marker, tmp_path / "alias")
    elif kind == "writable":
        marker.chmod(0o666)
    else:
        original = os.fstat

        def info(fd):
            result = original(fd)
            if result.st_ino == marker.stat().st_ino:
                values = list(result)
                values[4] = result.st_uid + 1
                return os.stat_result(values)
            return result

        monkeypatch.setattr(os, "fstat", info)
    old(stale)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert stale.exists()


def test_missing_namespace_is_a_noop(tmp_path):
    assert scratch.sweep(tmp_path, 3600) == 0


def test_replacement_during_final_unlink_is_preserved(tmp_path, monkeypatch):
    stale = abandoned(tmp_path)
    inode = stale.stat().st_ino
    replacement = tmp_path / "unmarked"
    replacement.mkdir()
    original = os.unlink
    swapped = False

    def unlink(path, *, dir_fd=None):
        nonlocal swapped
        if path == scratch.MARKER and not swapped and os.fstat(dir_fd).st_ino == inode:
            swapped = True
            stale.rename(tmp_path / "original")
            replacement.rename(stale)
        return original(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", unlink)
    assert scratch.sweep(tmp_path, 3600) == 0
    assert swapped
    assert stale.is_dir()


def test_scratch_works_where_proc_does_not_exist(tmp_path, monkeypatch):
    """macOS has no /proc: creating, leasing and sweeping must not use it."""
    stale = abandoned(tmp_path)
    (stale / "left-behind").mkdir()
    old(stale)

    def deny(real):
        def guarded(path, *args, **kwargs):
            if isinstance(path, str | bytes | os.PathLike) and os.fsdecode(path).startswith(
                "/proc"
            ):
                raise FileNotFoundError(path)
            return real(path, *args, **kwargs)

        return guarded

    for name in ("open", "mkdir", "stat", "lstat", "scandir", "listdir"):
        monkeypatch.setattr(os, name, deny(getattr(os, name)))

    with scratch.directory(str(tmp_path), prefix="media-job-") as path:
        (path / "nested").mkdir()
        (path / "nested" / "audio.wav").write_bytes(b"x")
        assert path.name.startswith("media-job-")
    assert not path.exists()

    assert scratch.sweep(tmp_path, 3600) == 1
    assert not stale.exists()


def test_a_taken_scratch_name_is_retried_and_exhaustion_is_an_error(tmp_path, monkeypatch):
    names = iter(["aa", "aa", "bb"])
    monkeypatch.setattr(scratch.secrets, "token_hex", lambda _: next(names))
    with (
        scratch.directory(str(tmp_path), prefix="media-job-") as first,
        scratch.directory(str(tmp_path), prefix="media-job-") as second,
    ):
        assert (first.name, second.name) == ("media-job-aa", "media-job-bb")

    monkeypatch.setattr(scratch.secrets, "token_hex", lambda _: "cc")
    with (
        scratch.directory(str(tmp_path), prefix="media-job-"),
        pytest.raises(FileExistsError),
        scratch.directory(str(tmp_path), prefix="media-job-"),
    ):
        pass
