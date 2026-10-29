"""Private worker scratch with lifetime locks and crash cleanup (#93).

Only directories created here, inside our private namespace, are sweep candidates.
Legacy and unrelated files are deliberately left for operator inspection.
"""

import fcntl
import logging
import os
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
def directory(root: str | None, *, prefix: str) -> Iterator[Path]:
    """Hold a shared lifetime lock until cleanup; process death releases it."""
    parent = Path(root or tempfile.gettempdir()) / NAMESPACE
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink():
        raise OSError("scratch namespace must not be a symlink")
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        with (path / MARKER).open("xb") as marker:
            fcntl.flock(marker, fcntl.LOCK_SH)
            marker.write(MAGIC)
            marker.flush()
            try:
                yield path
            finally:
                # Keep the lock held while removing the directory, so a sweep
                # cannot race normal context-manager cleanup.
                shutil.rmtree(path)
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)
        raise


def sweep(root: Path, max_age_seconds: int) -> int:
    """Remove stale owned directories after nonblocking acquisition of their lock."""
    parent = root / NAMESPACE
    if parent.is_symlink() or not parent.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - max_age_seconds
    for entry in parent.iterdir():
        try:
            before = entry.lstat()
            if not stat.S_ISDIR(before.st_mode):
                continue
            descriptor = os.open(entry / MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as marker:
                if not stat.S_ISREG(os.fstat(marker.fileno()).st_mode):
                    continue
                try:
                    fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                if marker.read(len(MAGIC) + 1) != MAGIC:
                    continue
                current = entry.lstat()
                if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                    continue
                newest = max([current.st_mtime, *(p.lstat().st_mtime for p in entry.rglob("*"))])
                if newest >= cutoff:
                    continue
                shutil.rmtree(entry)
                removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("scratch entry not removed", extra={"path": str(entry)})
    return removed
