"""Bounds on S3 writes: how long a stalled request can hold a worker, and how many
uploads run at once (#228 item 2, review of #256)."""

import asyncio
import threading
import time
from typing import Any

import pytest

from listenup.modules.content.writes import store
from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.config import Settings
from listenup.platform.storage import WRITE_THREADS, S3Storage, StorageWriteUncertain
from listenup.worker import SHUTDOWN_GRACE_SECONDS


def test_a_stalled_request_ends_within_the_worker_shutdown_grace() -> None:
    """Draining on cancellation waits for the upload thread, so the worst case of one
    request (every attempt waits out the connect and read timeouts) must fit in the
    time a stopping worker gives its jobs."""
    config = S3Storage(Settings())._client.meta.config
    attempts = config.retries["total_max_attempts"]
    worst_case = attempts * (config.connect_timeout + config.read_timeout)
    assert worst_case <= SHUTDOWN_GRACE_SECONDS


@pytest.mark.anyio
async def test_more_uploads_than_threads_queue_and_all_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = S3Storage(Settings())
    lock = threading.Lock()
    running = peak = done = 0

    def upload(**kwargs: Any) -> None:
        nonlocal running, peak, done
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1
            done += 1

    monkeypatch.setattr(storage._client, "put_object", upload)
    count = WRITE_THREADS * 3
    await asyncio.gather(*(storage.put(f"users/1/{n}", b"x", "audio/mp4") for n in range(count)))
    assert done == count
    assert peak <= WRITE_THREADS


@pytest.mark.anyio
async def test_a_cancelled_caller_still_gets_its_queued_upload_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upload waiting for a free thread cannot be withdrawn: the caller's fence stays
    until it has run (documented behaviour, so shutdown waits for the queue)."""
    storage = S3Storage(Settings())
    release = threading.Event()
    lock = threading.Lock()
    started: list[str] = []

    def upload(**kwargs: Any) -> None:
        with lock:
            started.append(kwargs["Key"])
        assert release.wait(5)

    monkeypatch.setattr(storage._client, "put_object", upload)
    busy = [
        asyncio.create_task(finish_on_cancel(storage.put(f"users/1/busy-{n}", b"x", "a/b")))
        for n in range(WRITE_THREADS)
    ]
    try:
        while len(started) < WRITE_THREADS:
            await asyncio.sleep(0.01)
        queued = asyncio.create_task(finish_on_cancel(storage.put("users/1/queued", b"x", "a/b")))
        await asyncio.sleep(0.05)
        queued.cancel()
        await asyncio.sleep(0.05)
        assert not queued.done(), "caller left while its upload was still queued"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await queued
        await asyncio.gather(*busy)
    assert "users/1/queued" in started


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_retained_task", [False, True])
async def test_the_conversion_write_wrapper_waits_for_the_thread(
    monkeypatch: pytest.MonkeyPatch, cancel_retained_task: bool
) -> None:
    """`registered_write` keeps its registration when a write is uncertain. A cancelled
    `store` returns only after the upload thread has finished; when shutdown cancels
    the retained task itself, the write is reported uncertain so the fence stays."""
    storage = S3Storage(Settings())
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def upload(**kwargs: Any) -> None:
        started.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    monkeypatch.setattr(storage._client, "put_object", upload)
    caller = asyncio.create_task(store(storage.put("users/1/peaks.json", b"{}", "a/b")))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        caller.cancel()
        if cancel_retained_task:
            for child in asyncio.all_tasks():
                if child.get_coro().__qualname__.endswith("tracked"):  # type: ignore[union-attr]
                    child.cancel()
        await asyncio.sleep(0.05)
        assert not caller.done(), "store returned with a live upload thread"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await caller
    assert finished.is_set()
    if cancel_retained_task:
        assert isinstance(raised.value.__cause__, StorageWriteUncertain)
    else:
        assert raised.value.__cause__ is None
