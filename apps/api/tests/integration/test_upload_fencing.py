"""Conversion and export must never outlive their deletion fences (DR-1)."""

import asyncio
import dataclasses
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from listenup.modules.content import ffmpeg
from listenup.modules.content import jobs as conversion
from listenup.modules.content.domain.media import Probe
from listenup.modules.export import jobs as export
from listenup.modules.identity import jobs as identity
from listenup.platform import jobs as platform_jobs
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, run_handler
from listenup.platform.storage import S3Storage, use_storage
from listenup.platform.storage_fence import StorageWriteInProgress
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import ClientFactory, FakeStorage, client_factory, learner_id
from tests.integration.test_account_deletion import delete_me, deletion_request, make_due
from tests.integration.test_conversion import add_file
from tests.integration.test_export import request_export


class PausedStorage(FakeStorage):
    """Run the production adapter against a controlled synchronous S3 boundary."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, pause_peaks: bool) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.adapter = S3Storage(Settings())

        def write(key: str, data: bytes, content_type: str, pause: bool) -> None:
            if pause:
                self.started.set()
                assert self.release.wait(10), "test did not release upload"
            self.arrive(key, len(data), content_type, data)
            if pause:
                self.finished.set()

        def upload_file(path: str, bucket: str, key: str, ExtraArgs: dict[str, str]) -> None:
            # Read after the barrier: cancellation must retain scratch files too.
            if not pause_peaks:
                self.started.set()
                assert self.release.wait(10)
            write(key, Path(path).read_bytes(), ExtraArgs["ContentType"], False)
            if not pause_peaks:
                self.finished.set()

        def put_object(**args: Any) -> None:
            write(args["Key"], args["Body"], args["ContentType"], pause_peaks)

        monkeypatch.setattr(self.adapter._client, "upload_file", upload_file)
        monkeypatch.setattr(self.adapter._client, "put_object", put_object)

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        await self.adapter.put_file(key, path, content_type)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self.adapter.put(key, data, content_type)


@pytest.fixture
def race_storage(monkeypatch: pytest.MonkeyPatch, writer: str) -> Iterator[PausedStorage]:
    storage = PausedStorage(monkeypatch, pause_peaks=writer == "conversion-peaks")
    use_storage(storage)
    yield storage
    storage.release.set()
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, race_storage: PausedStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, race_storage)


@pytest.mark.parametrize("writer", ["conversion-file", "conversion-peaks", "export"])
@pytest.mark.parametrize("interruption", ["cancel", "timeout", "connection-loss"])
def test_upload_finishes_before_deletion_and_purge_can_complete(
    make_client: ClientFactory,
    migrated_url: str,
    race_storage: PausedStorage,
    writer: str,
    interruption: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def probe(path: Path) -> Probe:
        return Probe(frozenset({"mp3"}), 35_000, True, False)

    async def convert(source: Path, target: Path, *, video: bool) -> ffmpeg.Converted:
        target.write_bytes(b"playback")
        return ffmpeg.Converted([1, 2], False)

    monkeypatch.setattr(conversion.ffmpeg, "probe", probe)
    monkeypatch.setattr(conversion.ffmpeg, "convert", convert)
    client = make_client()
    learner = uuid.UUID(learner_id(client))
    if writer == "export":
        name = export.BUILD_ARCHIVE
        args = {"export_id": str(request_export(client)["id"]), "user_id": str(learner)}
    else:
        source = tmp_path / "source.mp3"
        source.write_bytes(b"source")
        added = add_file(client, race_storage, source, migrated_url)
        name = conversion.CONVERT_UPLOAD
        args = {
            "media_object_id": added.media_id,
            "upload_id": added.upload_id,
            "user_id": str(learner),
        }
    entry = platform_jobs._registry[name]
    monkeypatch.setitem(
        platform_jobs._registry,
        name,
        dataclasses.replace(
            entry, spec=dataclasses.replace(entry.spec, timeout=timedelta(seconds=5))
        ),
    )

    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url) + "?application_name=upload-race")
        purge_database = Database(conninfo_to_url(migrated_url))
        upload = asyncio.create_task(run_handler(name, JobDeps(database, None, 1), **args))
        deletion: asyncio.Task[Any] | None = None
        try:
            assert await asyncio.to_thread(race_storage.started.wait, 5)
            deletion = asyncio.create_task(asyncio.to_thread(delete_me, client))
            if interruption == "connection-loss":
                with psycopg.connect(migrated_url, autocommit=True) as conn:
                    pid = conn.execute(
                        "SELECT pid FROM pg_stat_activity WHERE application_name = 'upload-race' "
                        "AND state = 'idle in transaction'"
                    ).fetchone()
                    assert pid is not None
                    conn.execute("SELECT pg_terminate_backend(%s)", [pid[0]])
                assert (await asyncio.wait_for(deletion, 5)).status_code == 202
                make_due(migrated_url, learner)
                request = str(deletion_request(migrated_url, learner)["id"])
                with pytest.raises(StorageWriteInProgress):
                    await identity.purge_account(JobDeps(purge_database, None, 1), request)
                assert deletion_request(migrated_url, learner)["status"] == "pending"
            else:
                if interruption == "cancel":
                    upload.cancel()
                    await asyncio.sleep(0.03)
                    upload.cancel()  # shutdown can cancel a timed-out job again
                else:
                    await asyncio.sleep(5.1)
                await asyncio.sleep(0.03)
                assert not upload.done(), "upload thread escaped the job's fence"
                assert not deletion.done(), "deletion passed an unfinished upload"
            assert not race_storage.finished.is_set()
        finally:
            race_storage.release.set()
            expected = {
                "cancel": asyncio.CancelledError,
                "timeout": TimeoutError,
                "connection-loss": DBAPIError,
            }[interruption]
            with pytest.raises(expected):
                await upload
            if deletion is not None:
                assert (await deletion).status_code == 202
            await database.dispose()
        try:
            assert race_storage.finished.is_set()
            make_due(migrated_url, learner)
            request = str(deletion_request(migrated_url, learner)["id"])
            await identity.purge_account(JobDeps(purge_database, None, 1), request)
            assert deletion_request(migrated_url, learner)["status"] == "completed"
            assert not any(key.startswith(f"users/{learner}/") for key in race_storage.objects)
        finally:
            await purge_database.dispose()

    asyncio.run(run())
