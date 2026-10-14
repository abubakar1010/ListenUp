"""Native asyncio cancellation must not abandon a synchronous S3 writer."""

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.config import Settings
from listenup.platform.storage import S3Storage, StorageWriteUncertain


@pytest.mark.anyio
@pytest.mark.parametrize("file_upload", [False, True])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("cancel_children", [False, True])
async def test_cancelled_upload_waits_for_the_thread_even_after_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_upload: bool,
    fails: bool,
    cancel_children: bool,
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
    task = asyncio.create_task(finish_on_cancel(operation))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        for _ in range(2):
            task.cancel()
            if cancel_children:
                # asyncio.run shutdown can cancel retained upload tasks directly.
                for child in asyncio.all_tasks():
                    name = child.get_coro().__qualname__
                    if name.startswith("S3Storage.put") or name == "run_sync":
                        child.cancel()
            await asyncio.sleep(0.02)
            assert not task.done(), "caller released its fence with a live upload thread"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await task
        if fails:
            assert isinstance(raised.value.__cause__, StorageWriteUncertain)
    assert finished.is_set()


@pytest.mark.anyio
async def test_upload_failure_is_reported_when_the_caller_was_not_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = S3Storage(Settings())

    def fail(**kwargs: Any) -> None:
        raise RuntimeError("upload refused")

    monkeypatch.setattr(storage._client, "put_object", fail)
    with pytest.raises(StorageWriteUncertain) as raised:
        await storage.put("users/1/file", b"data", "audio/mp4")
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "upload refused"
