"""Bounds on S3 writes: how long a stalled write can hold a stopping worker, and how many
uploads run at once (#228 item 2, reviews of #256 and #262)."""

import asyncio
import contextlib
import re
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from listenup.modules.content.writes import store
from listenup.platform import storage as storage_module
from listenup.platform.config import Settings
from listenup.platform.storage import (
    WRITE_THREADS,
    S3Storage,
    StorageWriteUncertain,
    stalled_request_seconds,
    write_drain_seconds,
)
from listenup.worker import SHUTDOWN_GRACE_SECONDS

REPO = Path(__file__).resolve().parents[4]
COMPOSE_FILES = ("infra/compose/compose.yml", "infra/compose/compose.prod.yml")
WORKERS = ("worker", "worker-media")
HANG_UP_SECONDS = 3


def seconds(duration: str) -> int:
    """A Compose duration such as `2m`, `90s` or `1m30s`, in seconds."""
    parts = re.findall(r"(\d+)([hms])", duration)
    assert parts and "".join(n + u for n, u in parts) == duration, duration
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts)


def test_the_write_client_bounds_each_attempt_and_retries_once() -> None:
    config = S3Storage(Settings())._writer.meta.config
    assert config.connect_timeout == storage_module.CONNECT_TIMEOUT_SECONDS
    assert config.read_timeout == storage_module.READ_TIMEOUT_SECONDS
    # botocore's `max_attempts` counts retries after the first attempt.
    assert config.retries["total_max_attempts"] == 1 + storage_module.MAX_RETRIES


def test_reads_deletes_and_signing_keep_botocores_defaults() -> None:
    """Only drained writes need the tight bounds; the other calls are not waited for at
    shutdown and keep botocore's longer timeouts and legacy retries (five attempts)."""
    storage = S3Storage(Settings())
    for client in (storage._client, storage._signer):
        config = client.meta.config
        assert (config.connect_timeout, config.read_timeout) == (60, 60)
        assert config.retries in (None, {"mode": "legacy"})


@pytest.mark.parametrize("compose", COMPOSE_FILES)
@pytest.mark.parametrize("service", WORKERS)
def test_a_stopping_worker_is_killed_only_after_its_grace_and_the_write_drain(
    compose: str, service: str
) -> None:
    """procrastinate waits SHUTDOWN_GRACE_SECONDS, then cancels the jobs and waits for
    them without a limit; a cancelled write drains its stalled requests first. Docker's
    default stop timeout (10 s) would kill the worker before either."""
    services = yaml.safe_load((REPO / compose).read_text())["services"]
    stop = seconds(services[service]["stop_grace_period"])
    assert stop >= SHUTDOWN_GRACE_SECONDS + write_drain_seconds()


class StubS3:
    """A local server that answers CreateMultipartUpload and then goes silent: on every
    part (`stall="parts"`), or only on CompleteMultipartUpload (`stall="complete"`)."""

    def __init__(self, stall: str) -> None:
        self.stall = stall
        self.requests: list[str] = []
        self._lock = threading.Lock()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self._server.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        # Hang up on a silent request after a while, so a client without bounds makes the
        # test fail on its duration instead of hanging it.
        conn.settimeout(HANG_UP_SECONDS)
        with conn, conn.makefile("rb") as stream, contextlib.suppress(OSError):
            while True:
                line = stream.readline().decode().strip()
                if not line:
                    return
                headers = {}
                while (header := stream.readline().decode().strip()) != "":
                    name, _, value = header.partition(":")
                    headers[name.lower()] = value.strip()
                with self._lock:
                    self.requests.append(line)
                method, target = line.split()[:2]
                is_part = method == "PUT" and "partNumber=" in target
                if self.stall == "parts" and is_part:
                    conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                    self._drain(stream)  # take the body, never answer
                    return
                if method == "POST" and target.endswith("?uploads"):
                    self._reply(conn, InitiateMultipartUploadResult)
                    continue
                if is_part:
                    if headers.get("expect") == "100-continue":
                        conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                    stream.read(int(headers["content-length"]))
                    self._reply(conn, b"", etag=True)
                    continue
                self._drain(stream)  # CompleteMultipartUpload and the abort: silent
                return

    @staticmethod
    def _drain(stream: Any) -> None:
        with contextlib.suppress(OSError):
            while stream.read(65536):
                pass

    @staticmethod
    def _reply(conn: socket.socket, body: bytes, etag: bool = False) -> None:
        extra = b'ETag: "e"\r\n' if etag else b""
        conn.sendall(b"HTTP/1.1 200 OK\r\n%sContent-Length: %d\r\n\r\n" % (extra, len(body)))
        conn.sendall(body)


InitiateMultipartUploadResult = (
    b'<?xml version="1.0" encoding="UTF-8"?><InitiateMultipartUploadResult>'
    b"<Bucket>listenup</Bucket><Key>users/1/big</Key><UploadId>u1</UploadId>"
    b"</InitiateMultipartUploadResult>"
)


@pytest.fixture
def small_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the timeouts and the multipart sizes so a stalled upload ends quickly."""
    monkeypatch.setattr(storage_module, "CONNECT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(storage_module, "READ_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(
        storage_module,
        "TRANSFER_CONFIG",
        storage_module.TransferConfig(
            multipart_threshold=5 * 1024**2, multipart_chunksize=5 * 1024**2, max_concurrency=2
        ),
    )


@pytest.fixture
def big_file(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "big.mp4"
    path.write_bytes(b"\0" * (16 * 1024**2))  # four parts of 5 MiB, two at a time
    yield path


@pytest.mark.anyio
@pytest.mark.parametrize("stall", ["parts", "complete"])
@pytest.mark.usefixtures("small_bounds")
async def test_a_stalled_multipart_upload_ends_within_the_write_drain(
    big_file: Path, stall: str
) -> None:
    """A multipart upload is several requests. When storage stops answering, the
    stalled request and the abort that follows it are the only two that wait: parts
    not yet sent are skipped once one has failed."""
    server = StubS3(stall)
    try:
        storage = S3Storage(Settings(s3_endpoint_url=server.url))
        started = time.monotonic()
        with pytest.raises(StorageWriteUncertain):
            await storage.put_file("users/1/big", big_file, "video/mp4")
        elapsed = time.monotonic() - started
    finally:
        server.close()
    assert elapsed <= write_drain_seconds()
    parts = {int(r.split("partNumber=")[1].split()[0]) for r in server.requests if "partN" in r}
    assert parts == ({1, 2} if stall == "parts" else {1, 2, 3, 4})
    assert any(r.startswith("DELETE ") and "uploadId=u1" in r for r in server.requests)


def test_the_drain_counts_two_stalled_requests_with_their_retries() -> None:
    """Each attempt can wait out the connect timeout, botocore's one-second wait for
    `100 Continue`, a body send (urllib3 sends under the connect timeout) and the read
    timeout; the one retry waits up to a second first. These are idle bounds: a server
    that keeps trickling bytes is not stalled and is not bounded."""
    attempt = 2 * 3 + 1 + 10
    assert stalled_request_seconds() == 2 * attempt + 1
    assert write_drain_seconds() == 2 * stalled_request_seconds()


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

    monkeypatch.setattr(storage._writer, "put_object", upload)
    count = WRITE_THREADS * 3
    await asyncio.gather(*(storage.put(f"users/1/{n}", b"x", "audio/mp4") for n in range(count)))
    assert done == count
    assert peak <= WRITE_THREADS


@pytest.mark.anyio
async def test_a_cancelled_caller_still_gets_its_queued_upload_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upload waiting for a free thread cannot be withdrawn: a bare `put` cancelled
    while queued returns only after its upload has run (so shutdown waits for the queue)."""
    storage = S3Storage(Settings())
    release = threading.Event()
    lock = threading.Lock()
    started: list[str] = []

    def upload(**kwargs: Any) -> None:
        with lock:
            started.append(kwargs["Key"])
        assert release.wait(5)

    monkeypatch.setattr(storage._writer, "put_object", upload)
    busy = [
        asyncio.create_task(storage.put(f"users/1/busy-{n}", b"x", "a/b"))
        for n in range(WRITE_THREADS)
    ]
    try:
        async with asyncio.timeout(5):
            while len(started) < WRITE_THREADS:
                await asyncio.sleep(0.01)
        queued = asyncio.create_task(storage.put("users/1/queued", b"x", "a/b"))
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

    monkeypatch.setattr(storage._writer, "put_object", upload)
    caller = asyncio.create_task(store(storage.put("users/1/peaks.json", b"{}", "a/b")))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        caller.cancel()
        if cancel_retained_task:
            # The task `store` runs its write in (what asyncio.run cancels at shutdown).
            retained = [
                child
                for child in asyncio.all_tasks()
                if getattr(child.get_coro(), "__qualname__", "") == "store.<locals>.tracked"
            ]
            assert len(retained) == 1, "store no longer runs its write in `tracked`"
            retained[0].cancel()
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
