"""Owned scratch survives active work and is reclaimed after a killed owner."""

import asyncio
import os
import subprocess
import sys
import time
from contextlib import contextmanager
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


@pytest.mark.parametrize(("depth", "descriptor_limit"), [(1200, None), (120, 64)])
def test_newest_mtime_handles_deep_trees_with_bounded_descriptors(
    tmp_path, depth, descriptor_limit
):
    root = tmp_path / "deep"
    root.mkdir()
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    created = 0
    try:
        for _ in range(depth):
            os.mkdir("d", dir_fd=current)
            os.utime(current, (1_000_000_000, 1_000_000_000))
            inner = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=current)
            os.close(current)
            current = inner
            created += 1
        os.utime(current, (2_000_000_000, 2_000_000_000))
        # A subprocess confines RLIMIT_NOFILE and catches leaked scanner handles
        # across repeated scans without depending on /proc or /dev/fd.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, resource, sys; "
                "from listenup.platform.scratch import _newest_mtime; "
                "limit = int(sys.argv[2]); "
                "limit and resource.setrlimit(resource.RLIMIT_NOFILE, "
                "(limit, resource.getrlimit(resource.RLIMIT_NOFILE)[1])); "
                "fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY); "
                "assert all(_newest_mtime(fd) == 2000000000 for _ in range(3)); "
                "os.close(fd)",
                str(root),
                str(descriptor_limit or 0),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr[-2000:]
    finally:
        # Avoid recursive cleanup and joined paths beyond macOS's PATH_MAX.
        try:
            for _ in range(created):
                parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY, dir_fd=current)
                os.close(current)
                current = parent
                os.rmdir("d", dir_fd=current)
        finally:
            os.close(current)


@pytest.mark.parametrize("moment", ["stat", "open"])
def test_child_removed_during_scan_does_not_block_other_entries(tmp_path, monkeypatch, moment):
    stale, other = abandoned(tmp_path), abandoned(tmp_path)
    (stale / "vanishing").mkdir()
    old(stale)
    real_scandir, real_open = os.scandir, os.open
    removed = False

    def vanish(descriptor):
        nonlocal removed
        os.rmdir("vanishing", dir_fd=descriptor)
        then = time.time() - 7200
        os.utime(descriptor, (then, then))
        removed = True

    class Child:
        def __init__(self, child, descriptor):
            self.child, self.descriptor = child, descriptor
            self.name = child.name

        def stat(self, **kwargs):
            if moment == "stat" and self.name == "vanishing" and not removed:
                vanish(self.descriptor)
            return self.child.stat(**kwargs)

        def is_dir(self, **kwargs):
            return self.child.is_dir(**kwargs)

    @contextmanager
    def scan(descriptor):
        with real_scandir(descriptor) as children:
            yield (Child(child, descriptor) for child in children)

    def open_child(path, flags, *args, dir_fd=None, **kwargs):
        if moment == "open" and path == "vanishing" and not removed:
            vanish(dir_fd)
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "scandir", scan)
    monkeypatch.setattr(os, "open", open_child)
    assert scratch.sweep(tmp_path, 3600) == (1 if moment == "stat" else 2)
    assert removed
    assert not other.exists()
    assert stale.exists() == (moment == "stat")


def test_sweep_keeps_recent_nested_file_when_its_parents_are_old(tmp_path):
    stale = abandoned(tmp_path)
    nested = stale / "nested"
    nested.mkdir()
    recent = nested / "recent"
    recent.write_bytes(b"keep")
    old(stale)
    now = time.time()
    os.utime(recent, (now, now))
    assert scratch.sweep(tmp_path, 3600) == 0
    assert recent.read_bytes() == b"keep"


@pytest.mark.parametrize("failure", [None, "open", "scandir"])
def test_scan_closes_owned_handles_on_success_and_failure(tmp_path, monkeypatch, failure):
    (tmp_path / "parent" / "leaf").mkdir(parents=True)
    root = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    leaf_identity = (tmp_path / "parent" / "leaf").stat().st_ino
    real_open, real_dup, real_close, real_scandir = os.open, os.dup, os.close, os.scandir
    owned = set()
    scanners = 0

    def open_child(path, flags, **kwargs):
        if failure == "open" and path == "leaf":
            raise PermissionError("child open refused")
        descriptor = real_open(path, flags, **kwargs)
        owned.add(descriptor)
        return descriptor

    def duplicate(descriptor):
        duplicate = real_dup(descriptor)
        owned.add(duplicate)
        return duplicate

    def close(descriptor):
        owned.remove(descriptor)
        real_close(descriptor)

    @contextmanager
    def scan(descriptor):
        nonlocal scanners
        if failure == "scandir" and os.fstat(descriptor).st_ino == leaf_identity:
            raise PermissionError("child scan refused")
        with real_scandir(descriptor) as children:
            scanners += 1
            try:
                yield children
            finally:
                scanners -= 1

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", open_child)
            patch.setattr(os, "dup", duplicate)
            patch.setattr(os, "close", close)
            patch.setattr(os, "scandir", scan)
            if failure:
                with pytest.raises(PermissionError):
                    scratch._newest_mtime(root)
            else:
                scratch._newest_mtime(root)
            assert not owned
            assert scanners == 0
            assert os.fstat(root).st_ino == tmp_path.stat().st_ino
    finally:
        real_close(root)


def test_scan_never_follows_an_intermediate_directory_replaced_by_a_symlink(tmp_path, monkeypatch):
    stale, other = abandoned(tmp_path), abandoned(tmp_path)
    (stale / "parent" / "leaf").mkdir(parents=True)
    parent_identity = (stale / "parent").stat().st_ino
    target = tmp_path / "foreign"
    (target / "leaf").mkdir(parents=True)
    (target / "leaf" / "keep").write_bytes(b"safe")
    foreign_identities = {target.stat().st_ino, (target / "leaf").stat().st_ino}
    old(stale)
    original = os.scandir
    swapped = False

    @contextmanager
    def scan(descriptor):
        nonlocal swapped
        identity = os.fstat(descriptor).st_ino
        assert identity not in foreign_identities, "must never scan through the symlink"
        with original(descriptor) as children:
            yield children
        if identity == parent_identity and not swapped:
            (stale / "parent").rename(stale / "original")
            (stale / "parent").symlink_to(target, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(os, "scandir", scan)
    assert scratch.sweep(tmp_path, 3600) == 1
    assert swapped
    assert stale.exists() and not other.exists()
    assert (target / "leaf" / "keep").read_bytes() == b"safe"
