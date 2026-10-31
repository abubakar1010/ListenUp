"""Private worker scratch with lifetime locks and crash cleanup (#93).

Only directories created here, inside our private namespace, are sweep candidates.
Legacy and unrelated files are deliberately left for operator inspection. The
namespace must belong to this effective user and be inaccessible to other users;
code running as that same user is trusted not to tamper with live leases.
"""

import fcntl
import logging
import os
import secrets
import shutil
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
NAMESPACE = "listenup-scratch-v1"
MARKER = ".listenup-owner"
MAGIC = b"listenup-scratch-v1\n"


@contextmanager
def _private_directory(path: str | Path, *, dir_fd: int | None = None) -> Iterator[int]:
    # O_NOFOLLOW applies to the directory itself, not merely its marker.
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise OSError("scratch directory must be private and owned by the worker")
        yield descriptor
    finally:
        os.close(descriptor)


def _same(parent: int, name: str, descriptor: int) -> bool:
    named = os.stat(name, dir_fd=parent, follow_symlinks=False)
    opened = os.fstat(descriptor)
    return (named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino)


def _remove(parent: int, name: str, entry: int, marker: int) -> bool:
    """Remove through the opened directory; never traverse a replacement pathname."""
    if not _same(parent, name, entry) or not _same(entry, MARKER, marker):
        return False
    # Even a replacement after the check cannot redirect these relative operations
    # into the replacement directory. shutil's nested removal is fd/symlink safe.
    with os.scandir(entry) as children:
        for child in children:
            if child.name == MARKER:
                continue
            if child.is_dir(follow_symlinks=False):
                shutil.rmtree(child.name, dir_fd=entry)
            else:
                os.unlink(child.name, dir_fd=entry)
    if not _same(parent, name, entry) or not _same(entry, MARKER, marker):
        return False
    os.unlink(MARKER, dir_fd=entry)
    # Only the now-empty, still-named owned directory can be unlinked.
    if not _same(parent, name, entry):
        return False
    os.rmdir(name, dir_fd=parent)
    return True


def _make_entry(namespace: int, prefix: str) -> str:
    """Create a private directory named `prefix` + random through the namespace
    descriptor, without /proc (absent on macOS); retry if the name is taken."""
    for _ in range(100):
        name = prefix + secrets.token_hex(8)
        try:
            os.mkdir(name, 0o700, dir_fd=namespace)
        except FileExistsError:
            continue
        return name
    raise FileExistsError(f"no free scratch name for prefix {prefix!r}")


def _newest_mtime(descriptor: int) -> float:
    """Newest modification time of a directory and everything below it, read through
    open descriptors so a replaced pathname is never followed. Iterative, so a deeply
    nested tree cannot exhaust the recursion limit; the caller keeps `descriptor`."""
    newest = os.fstat(descriptor).st_mtime
    pending: list[int] = []
    current = descriptor
    try:
        while True:
            with os.scandir(current) as children:
                for child in children:
                    newest = max(newest, child.stat(follow_symlinks=False).st_mtime)
                    if not child.is_dir(follow_symlinks=False):
                        continue
                    try:
                        pending.append(
                            os.open(
                                child.name,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current,
                            )
                        )
                    except FileNotFoundError:
                        continue
            if current != descriptor:
                os.close(current)
            if not pending:
                return newest
            current = pending.pop()
    except BaseException:
        for leftover in (*pending, *([current] if current != descriptor else [])):
            os.close(leftover)
        raise


@contextmanager
def directory(root: str | None, *, prefix: str) -> Iterator[Path]:
    """Hold a shared lifetime lock until cleanup; process death releases it."""
    parent = Path(root or tempfile.gettempdir()) / NAMESPACE
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink():
        raise OSError("scratch namespace must not be a symlink")
    with _private_directory(parent) as namespace:
        # Create relative to the validated namespace, including if its path moves.
        name = _make_entry(namespace, prefix)
        path = parent / name
        with _private_directory(name, dir_fd=namespace) as entry:
            descriptor = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=entry)
            with os.fdopen(descriptor, "wb") as marker:
                fcntl.flock(marker, fcntl.LOCK_SH)
                marker.write(MAGIC)
                marker.flush()
                try:
                    yield path
                finally:
                    # Keep the lock through cleanup and bind it to this entry.
                    _remove(namespace, name, entry, marker.fileno())


def _sweep(namespace: int, max_age_seconds: int) -> int:
    removed = 0
    cutoff = time.time() - max_age_seconds
    for name in os.listdir(namespace):
        try:
            with _private_directory(name, dir_fd=namespace) as entry:
                descriptor = os.open(
                    MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=entry
                )
                with os.fdopen(descriptor, "rb") as marker:
                    info = os.fstat(marker.fileno())
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.geteuid()
                        or info.st_mode & 0o022
                        or info.st_nlink != 1
                    ):
                        continue
                    try:
                        fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    if marker.read(len(MAGIC) + 1) != MAGIC:
                        continue
                    if _newest_mtime(entry) >= cutoff:
                        continue
                    removed += _remove(namespace, name, entry, marker.fileno())
        except FileNotFoundError:
            continue
        except (OSError, RecursionError):  # e.g. a tree too deep to remove safely
            logger.exception("scratch entry not removed", extra={"path": name})
    return removed


def sweep(root: Path, max_age_seconds: int) -> int:
    """Remove stale owned directories after nonblocking acquisition of their lock."""
    try:
        with _private_directory(root / NAMESPACE) as namespace:
            return _sweep(namespace, max_age_seconds)
    except FileNotFoundError:
        return 0
    except OSError:
        logger.exception("scratch namespace not swept", extra={"path": str(root / NAMESPACE)})
        return 0
