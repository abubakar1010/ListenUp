import asyncio

import pytest


@pytest.mark.anyio
@pytest.mark.parametrize("fails", [False, True])
async def test_cancelled_upload_drains_even_after_repeated_cancellation(fails):
    from listenup.platform.cancellation import finish_on_cancel

    started, finish = asyncio.Event(), asyncio.Event()

    async def upload():
        started.set()
        await finish.wait()
        if fails:
            raise OSError("upload uncertain")
        return "uploaded"

    task = asyncio.create_task(finish_on_cancel(upload()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError) as raised:
        await task
    assert isinstance(raised.value.__cause__, OSError) == fails


@pytest.mark.anyio
async def test_upload_error_keeps_storage_uncertainty(tmp_path, monkeypatch):
    from listenup.platform.config import Settings
    from listenup.platform.storage import S3Storage, StorageWriteUncertain

    storage = S3Storage(Settings())

    def lost_response(*args, **kwargs):
        raise OSError("response lost")

    monkeypatch.setattr(storage._client, "upload_file", lost_response)
    with pytest.raises(StorageWriteUncertain):
        await storage.put_file("users/test/cards/test/snippet.m4a", tmp_path / "input", "audio/mp4")
