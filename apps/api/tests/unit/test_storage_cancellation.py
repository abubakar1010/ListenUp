"""Native asyncio cancellation must not abandon a synchronous S3 writer (#228 item 2)."""

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.config import Settings
from listenup.platform.storage import S3Storage, StorageWriteUncertain


def cancel_retained_uploads() -> int:
    """What `asyncio.run` shutdown does to the task a cancelled caller left running."""
    cancelled = 0
    for child in asyncio.all_tasks():
        if child.get_coro().__qualname__.startswith("S3Storage.put"):  # type: ignore[union-attr]
            child.cancel()
            cancelled += 1
    return cancelled


@pytest.mark.anyio
@pytest.mark.parametrize("file_upload", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_upload_waits_for_the_thread_even_after_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_upload: bool,
    fails: bool,
) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    storage = S3Storage(Settings())

    def upload(*args: Any, **kwargs: Any) -> None:
        started.set()
        try:
            assert release.wait(5)
            if fails:
                raise RuntimeError("upload failed")
        finally:
            finished.set()

    monkeypatch.setattr(storage._client, "upload_file", upload)
    monkeypatch.setattr(storage._client, "put_object", upload)
    path = tmp_path / "file"
    path.write_bytes(b"data")
    operation = (
        storage.put_file("users/1/file", path, "audio/mp4")
        if file_upload
        else storage.put("users/1/file", b"data", "audio/mp4")
    )
    caller = asyncio.create_task(finish_on_cancel(operation))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        for _ in range(2):
            caller.cancel()
            await asyncio.sleep(0.02)
            assert cancel_retained_uploads() >= 1, "no retained upload task to cancel"
            await asyncio.sleep(0.02)
            assert not caller.done(), "caller released its fence with a live upload thread"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await caller
        if fails:
            expected = StorageWriteUncertain if file_upload else RuntimeError
            assert type(raised.value.__cause__) is expected
    assert finished.is_set()


@pytest.mark.anyio
async def test_upload_failure_is_reported_when_the_caller_was_not_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = S3Storage(Settings())

    def fail(**kwargs: Any) -> None:
        raise RuntimeError("upload refused")

    monkeypatch.setattr(storage._client, "put_object", fail)
    with pytest.raises(RuntimeError) as raised:
        await storage.put("users/1/file", b"data", "audio/mp4")
    assert str(raised.value) == "upload refused"


@pytest.mark.anyio
@pytest.mark.parametrize("file_upload", [False, True])
async def test_uploads_run_in_their_own_thread_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_upload: bool
) -> None:
    """Uploads must not queue behind `asyncio.to_thread` and DNS lookups, which share
    the loop's default executor (a handful of threads on a small host)."""
    storage = S3Storage(Settings())
    threads: list[str] = []

    def upload(*args: Any, **kwargs: Any) -> None:
        threads.append(threading.current_thread().name)

    monkeypatch.setattr(storage._client, "upload_file", upload)
    monkeypatch.setattr(storage._client, "put_object", upload)
    path = tmp_path / "file"
    path.write_bytes(b"data")
    if file_upload:
        await storage.put_file("users/1/file", path, "audio/mp4")
    else:
        await storage.put("users/1/file", b"data", "audio/mp4")
    assert len(threads) == 1
    assert threads[0].startswith("storage-write")
