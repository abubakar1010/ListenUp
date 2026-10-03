"""Convert an upload into the playback file and play it (#36: FR-CI-1, FR-CI-3, FR-CI-6,
NFR-SEC-2, NFR-SEC-3, NFR-PERF-1, NFR-PERF-4).

The test media is made with ffmpeg here, a few seconds of CPU at most; no binary
fixtures are committed. The API runs as a role with only the API's rights, so
row-level security is in force; the job runs as the migration owner, which bypasses
row-level security like the workers' role. Most tests use the in-memory storage; the
last one uses a real bucket and is skipped when no S3 server is reachable, unless
LISTENUP_REQUIRE_S3=1 (as in CI).
"""

import asyncio
import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import httpx
import psycopg
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient

from listenup.modules.content import jobs
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError
from listenup.platform.storage import Downloaded, S3Storage, Storage
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    confirm,
    key_of,
    learner_id,
    start,
)

# --- Test media -------------------------------------------------------------------------


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args], check=True, timeout=60
    )


TONE = ["-f", "lavfi", "-i", "sine=frequency=440:duration={seconds}"]
PICTURE = ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration={seconds}"]


def tone(seconds: int) -> list[str]:
    return [arg.format(seconds=seconds) for arg in TONE]


def picture(seconds: int) -> list[str]:
    return [arg.format(seconds=seconds) for arg in PICTURE]


@dataclass(frozen=True)
class Media:
    mp3: Path
    mp4: Path  # with a picture
    wav: Path
    short_mp3: Path  # 10 s
    silent_mp4: Path  # a picture without a sound track
    text_mp3: Path  # a text file with an .mp3 name


@pytest.fixture(scope="module")
def media(tmp_path_factory: pytest.TempPathFactory) -> Media:
    folder = tmp_path_factory.mktemp("media")
    files = Media(
        mp3=folder / "tone.mp3",
        mp4=folder / "talk.mp4",
        wav=folder / "tone.wav",
        short_mp3=folder / "short.mp3",
        silent_mp4=folder / "silent.mp4",
        text_mp3=folder / "notes.mp3",
    )
    ffmpeg(*tone(35), "-ac", "1", "-b:a", "32k", str(files.mp3))
    ffmpeg(
        *tone(35), *picture(35), "-map", "0:a", "-map", "1:v", "-shortest", "-c:v", "libx264",
        "-preset", "ultrafast", "-c:a", "aac", "-b:a", "32k", str(files.mp4),
    )  # fmt: skip
    ffmpeg(*tone(31), "-ac", "1", "-ar", "8000", str(files.wav))
    ffmpeg(*tone(10), "-ac", "1", "-b:a", "32k", str(files.short_mp3))
    ffmpeg(*picture(35), "-c:v", "libx264", "-preset", "ultrafast", str(files.silent_mp4))
    files.text_mp3.write_text("Shopping list: bread, milk, a better microphone.\n" * 50)
    return files


# --- Fixtures and helpers ---------------------------------------------------------------


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    jobs.use_storage(fake)
    yield fake
    jobs.use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


CONTENT_TYPES = {".mp3": "audio/mpeg", ".mp4": "video/mp4", ".wav": "audio/wav"}


@dataclass(frozen=True)
class Added:
    content_id: str
    media_id: str
    upload_id: str
    source_key: str


def add_file(
    client: TestClient, storage: FakeStorage, path: Path, migrated_url: str, **body: object
) -> Added:
    """Upload a file through the API with the fake storage and confirm it."""
    data = path.read_bytes()
    content_type = CONTENT_TYPES[path.suffix]
    target = start(client, filename=path.name, content_type=content_type, size=len(data)).json()
    key = key_of(target)
    storage.arrive(key, len(data), content_type, data)
    confirmed = confirm(client, target["upload_id"], **body)
    assert confirmed.status_code == 201, confirmed.text
    content_id = confirmed.json()["id"]
    with psycopg.connect(migrated_url) as conn:
        media_id = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id = %s", [content_id]
        ).fetchone()
    assert media_id is not None
    return Added(content_id, str(media_id[0]), target["upload_id"], key)


def run_job(migrated_url: str, added: Added, attempt: int = 1) -> None:
    """Run the job handler as a worker would, with the workers' rights."""

    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.convert_upload(
                JobDeps(database, None, attempt),
                media_object_id=added.media_id,
                upload_id=added.upload_id,
            )
        finally:
            await database.dispose()

    asyncio.run(run())


def media_row(migrated_url: str, media_id: str) -> dict[str, object] | None:
    with psycopg.connect(migrated_url) as conn:
        cursor = conn.execute(
            "SELECT status, error_code, duration_ms, has_video, playback_key, peaks_key, "
            "playback_bytes, fingerprint, ref_count, stage FROM content.media_objects "
            "WHERE id = %s",
            [media_id],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        names = [column.name for column in cursor.description or []]
        return dict(zip(names, row, strict=True))


def probe(data: bytes, folder: Path) -> dict[str, object]:
    path = folder / "probe.mp4"
    path.write_bytes(data)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


@pytest.fixture
def listener(migrated_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("LISTEN user_events")
        yield conn


def events_for(conn: psycopg.Connection[tuple[object, ...]], user: str) -> list[dict[str, str]]:
    found = []
    for note in conn.notifies(timeout=1.0):
        payload = json.loads(note.payload)
        if payload["u"] == user:
            found.append(payload)
    return found


# --- A real conversion ------------------------------------------------------------------


def test_an_mp3_becomes_a_playable_aac_file_with_peaks(
    client: TestClient,
    storage: FakeStorage,
    media: Media,
    migrated_url: str,
    listener: psycopg.Connection[tuple[object, ...]],
    tmp_path: Path,
) -> None:
    user = learner_id(client)
    added = add_file(client, storage, media.mp3, migrated_url)

    run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None
    assert row["status"] == "playable"
    assert row["error_code"] is None
    assert abs(int(row["duration_ms"]) - 35_000) < 200  # type: ignore[call-overload]
    assert row["has_video"] is False
    prefix = f"users/{user}/media/{added.media_id}/"
    assert row["playback_key"] == prefix + "playback.mp4"
    assert row["peaks_key"] == prefix + "peaks.json"
    playback = storage.data[prefix + "playback.mp4"]
    assert row["playback_bytes"] == len(playback)
    assert storage.objects[prefix + "playback.mp4"].content_type == "audio/mp4"

    # AAC-LC, mono, about 64 kbit/s, in MP4 with the index at the front (faststart).
    info = probe(playback, tmp_path)
    streams = info["streams"]
    assert isinstance(streams, list) and len(streams) == 1
    audio = streams[0]
    assert (audio["codec_name"], audio["profile"], audio["channels"]) == ("aac", "LC", 1)
    assert 50_000 < int(audio["bit_rate"]) < 80_000
    assert playback.find(b"moov") < playback.find(b"mdat")

    # Ten peaks a second, compact: well under 2 KB a minute.
    peaks = json.loads(storage.data[prefix + "peaks.json"])
    assert peaks["per_second"] == 10
    assert abs(len(peaks["peaks"]) - 350) <= 2
    assert all(0 <= value <= 100 for value in peaks["peaks"])
    assert max(peaks["peaks"]) > 0
    assert len(storage.data[prefix + "peaks.json"]) < 2048

    # The original is gone; the learner is told of each stage and the end, with the
    # content item's id (#40).
    assert added.source_key not in storage.objects
    assert added.source_key in storage.deleted
    progress = {"u": user, "t": "job.progress", "r": added.content_id}
    ready = {"u": user, "t": "content.ready", "r": added.content_id}
    assert events_for(listener, user) == [progress, progress, progress, ready]

    detail = client.get(f"/api/v1/contents/{added.content_id}").json()
    assert detail["status"] == "playable"
    assert detail["media_url"] == f"/api/v1/media/{added.media_id}"
    assert detail["peaks_url"] == f"/api/v1/media/{added.media_id}/peaks"
    assert detail["error_detail"] is None


def test_each_stage_is_recorded_while_the_job_runs_and_cleared_at_the_end(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    """A page that refetches after a `job.progress` event reads the stage (#40)."""
    added = add_file(client, storage, media.mp3, migrated_url)
    seen: list[tuple[str, object]] = []

    def stage_now(step: str) -> None:
        seen.append((step, client.get(f"/api/v1/contents/{added.content_id}").json()["stage"]))

    class Watching(FakeStorage):
        async def download(self, key: str, destination: Path) -> Downloaded | None:
            stage_now("download")
            return await storage.download(key, destination)

        async def put_file(self, key: str, path: Path, content_type: str) -> None:
            stage_now("store")
            await storage.put_file(key, path, content_type)

    watching = Watching()
    jobs.use_storage(watching)
    stage_now("before")
    run_job(migrated_url, added)

    assert seen == [("before", "waiting"), ("download", "checking"), ("store", "saving")]
    detail = client.get(f"/api/v1/contents/{added.content_id}").json()
    assert (detail["status"], detail["stage"]) == ("playable", None)


def test_the_fingerprint_is_the_sha256_of_the_original(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    import hashlib

    user = learner_id(client)
    added = add_file(client, storage, media.wav, migrated_url)

    run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None and row["status"] == "playable"
    sha256 = hashlib.sha256(media.wav.read_bytes()).hexdigest()
    assert row["fingerprint"] == f"upload:{user}:{sha256}"


def test_a_video_keeps_its_picture_only_when_asked(
    make_client: ClientFactory,
    storage: FakeStorage,
    media: Media,
    migrated_url: str,
    tmp_path: Path,
) -> None:
    plain = add_file(make_client(), storage, media.mp4, migrated_url)
    run_job(migrated_url, plain)
    row = media_row(migrated_url, plain.media_id)
    assert row is not None and row["status"] == "playable" and row["has_video"] is False
    info = probe(storage.data[str(row["playback_key"])], tmp_path)
    assert [s["codec_type"] for s in info["streams"]] == ["audio"]  # type: ignore[attr-defined]

    kept = add_file(make_client(), storage, media.mp4, migrated_url, keep_video=True)
    run_job(migrated_url, kept)

    row = media_row(migrated_url, kept.media_id)
    assert row is not None and row["status"] == "playable" and row["has_video"] is True
    info = probe(storage.data[str(row["playback_key"])], tmp_path)
    streams = info["streams"]
    assert isinstance(streams, list)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert video["codec_name"] == "h264"
    assert video["height"] <= 360
    assert storage.objects[str(row["playback_key"])].content_type == "video/mp4"


# --- Files that cannot be used ----------------------------------------------------------


@pytest.mark.parametrize(
    ("which", "code"),
    [
        ("text_mp3", "unsupported_media"),
        ("short_mp3", "clip_too_short"),
        ("silent_mp4", "no_audio_track"),
    ],
)
def test_an_unusable_file_fails_with_a_reason_and_is_not_retried(
    client: TestClient,
    storage: FakeStorage,
    media: Media,
    migrated_url: str,
    listener: psycopg.Connection[tuple[object, ...]],
    which: str,
    code: str,
) -> None:
    user = learner_id(client)
    added = add_file(client, storage, getattr(media, which), migrated_url)

    with pytest.raises(PermanentError):
        run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None
    assert (row["status"], row["error_code"]) == ("failed", code)
    assert row["playback_key"] is None
    assert added.source_key not in storage.objects
    assert row["stage"] is None
    assert events_for(listener, user)[-1] == {
        "u": user,
        "t": "content.ready",
        "r": added.content_id,
    }
    detail = client.get(f"/api/v1/contents/{added.content_id}").json()
    assert detail["status"] == "failed"
    assert detail["stage"] is None
    assert detail["error_code"] == code
    assert detail["error_detail"]
    assert detail["media_url"] is None
    assert client.get(f"/api/v1/media/{added.media_id}").json()["code"] == "media_not_ready"


def test_a_missing_original_fails_the_item(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    added = add_file(client, storage, media.mp3, migrated_url)
    storage.data.pop(added.source_key)

    with pytest.raises(PermanentError):
        run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None and (row["status"], row["error_code"]) == ("failed", "upload_missing")


def test_the_last_failed_attempt_marks_the_item_failed(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    added = add_file(client, storage, media.mp3, migrated_url)

    class Broken(FakeStorage):
        async def download(self, key: str, destination: Path) -> None:
            raise ConnectionError("storage is down")

    jobs.use_storage(Broken())
    with pytest.raises(ConnectionError):
        run_job(migrated_url, added, attempt=1)
    row = media_row(migrated_url, added.media_id)
    assert row is not None and row["status"] == "pending"  # retried later

    with pytest.raises(ConnectionError):
        run_job(migrated_url, added, attempt=5)
    row = media_row(migrated_url, added.media_id)
    assert row is not None and (row["status"], row["error_code"]) == ("failed", "processing_failed")


# --- Running again ----------------------------------------------------------------------


def test_a_second_run_changes_nothing(
    client: TestClient,
    storage: FakeStorage,
    media: Media,
    migrated_url: str,
    listener: psycopg.Connection[tuple[object, ...]],
) -> None:
    user = learner_id(client)
    added = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, added)
    first = media_row(migrated_url, added.media_id)
    stored = dict(storage.data)
    events_for(listener, user)

    run_job(migrated_url, added)

    assert media_row(migrated_url, added.media_id) == first
    assert storage.data == stored
    assert events_for(listener, user) == []


def test_a_run_after_a_crash_before_the_original_was_deleted_finishes_the_job(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    added = add_file(client, storage, media.mp3, migrated_url)
    original = storage.data[added.source_key]
    run_job(migrated_url, added)
    storage.arrive(added.source_key, len(original), "audio/mpeg", original)  # "not deleted"

    run_job(migrated_url, added)

    assert added.source_key not in storage.objects


def test_an_item_deleted_before_its_job_runs_is_skipped(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    added = add_file(client, storage, media.mp3, migrated_url)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM content.contents WHERE id = %s", [added.content_id])

    run_job(migrated_url, added)

    assert not [key for key in storage.objects if "/media/" in key]


# --- The same file twice ----------------------------------------------------------------


def test_the_same_file_twice_keeps_one_item(
    client: TestClient,
    storage: FakeStorage,
    media: Media,
    migrated_url: str,
    listener: psycopg.Connection[tuple[object, ...]],
) -> None:
    user = learner_id(client)
    first = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, first)
    events_for(listener, user)
    stored = {key for key in storage.objects if "/media/" in key}

    second = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, second)

    # The new item and its media object are gone; the first is untouched.
    assert media_row(migrated_url, second.media_id) is None
    kept = media_row(migrated_url, first.media_id)
    assert kept is not None and kept["status"] == "playable" and kept["ref_count"] == 1
    assert client.get(f"/api/v1/contents/{second.content_id}").status_code == 404
    library = client.get("/api/v1/contents").json()["items"]
    assert [item["id"] for item in library] == [first.content_id]
    # Nothing was converted, the duplicate original is gone, its upload no longer counts.
    assert {key for key in storage.objects if "/media/" in key} == stored
    assert second.source_key not in storage.objects
    assert client.get("/api/v1/uploads/usage").json()["used_bytes"] == media.mp3.stat().st_size
    # The page showing the new item refetches and learns it is gone.
    assert events_for(listener, user) == [
        {"u": user, "t": "job.progress", "r": second.content_id},
        {"u": user, "t": "content.ready", "r": second.content_id},
    ]


def test_the_same_file_from_two_learners_is_never_shared(
    make_client: ClientFactory, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    one, two = make_client(), make_client()
    first = add_file(one, storage, media.mp3, migrated_url)
    second = add_file(two, storage, media.mp3, migrated_url)

    run_job(migrated_url, first)
    run_job(migrated_url, second)

    assert media_row(migrated_url, first.media_id)["status"] == "playable"  # type: ignore[index]
    assert media_row(migrated_url, second.media_id)["status"] == "playable"  # type: ignore[index]


def test_a_file_whose_earlier_item_was_deleted_is_converted_again(
    client: TestClient, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    user = learner_id(client)
    first = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, first)
    with psycopg.connect(migrated_url) as conn:
        # The learner deleted the item; its media object waits for the orphan sweep.
        conn.execute("DELETE FROM content.contents WHERE id = %s", [first.content_id])

    second = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, second)

    assert media_row(migrated_url, first.media_id) is None
    assert not [
        key for key in storage.objects if key.startswith(f"users/{user}/media/{first.media_id}/")
    ]
    row = media_row(migrated_url, second.media_id)
    assert row is not None and row["status"] == "playable"


# --- Playing it -------------------------------------------------------------------------


def test_the_owner_is_redirected_to_a_signed_url_and_anyone_else_gets_404(
    make_client: ClientFactory, storage: FakeStorage, media: Media, migrated_url: str
) -> None:
    owner, other = make_client(), make_client()
    added = add_file(owner, storage, media.mp3, migrated_url)

    pending = owner.get(f"/api/v1/media/{added.media_id}", follow_redirects=False)
    assert (pending.status_code, pending.json()["code"]) == (409, "media_not_ready")

    run_job(migrated_url, added)

    played = owner.get(f"/api/v1/media/{added.media_id}", follow_redirects=False)
    assert played.status_code == 307
    user = learner_id(owner)
    assert played.headers["location"].startswith(
        f"http://storage.test/bucket/users/{user}/media/{added.media_id}/playback.mp4"
    )
    assert played.headers["cache-control"] == "private, no-store"
    peaks = owner.get(f"/api/v1/media/{added.media_id}/peaks", follow_redirects=False)
    assert peaks.status_code == 307
    assert peaks.headers["location"].endswith("/peaks.json?sig")

    for path in (f"/api/v1/media/{added.media_id}", f"/api/v1/media/{added.media_id}/peaks"):
        refused = other.get(path, follow_redirects=False)
        assert (refused.status_code, refused.json()["code"]) == (404, "media_not_found")
    assert other.get(f"/api/v1/contents/{added.content_id}").status_code == 404
    assert owner.get(f"/api/v1/media/{uuid.uuid4()}").status_code == 404


def test_media_needs_a_signed_in_learner(make_client: ClientFactory) -> None:
    client = make_client()
    client.post("/api/v1/auth/logout")
    assert client.get(f"/api/v1/media/{uuid.uuid4()}").status_code == 401


# --- With a real bucket -----------------------------------------------------------------


@pytest.fixture(scope="module")
def bucket() -> Iterator[str]:
    settings = Settings(s3_bucket=f"listenup-test-{uuid.uuid4().hex[:12]}")
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path"}, connect_timeout=3, retries={"max_attempts": 1}
        ),
    )
    try:
        s3.create_bucket(Bucket=settings.s3_bucket)
    except (BotoCoreError, ClientError) as error:
        if os.environ.get("LISTENUP_REQUIRE_S3") == "1":
            raise
        pytest.skip(f"S3 storage is not reachable: {error}")
    yield settings.s3_bucket
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket):
        for obj in page.get("Contents", []):
            s3.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=settings.s3_bucket)


def test_a_real_upload_is_converted_and_plays_with_range_requests(
    make_client: ClientFactory, media: Media, migrated_url: str, bucket: str
) -> None:
    client = make_client(fake=False, s3_bucket=bucket)
    real: Storage = S3Storage(Settings(s3_bucket=bucket))
    jobs.use_storage(real)
    try:
        data = media.mp4.read_bytes()
        target = start(client, filename="talk.mp4", content_type="video/mp4", size=len(data))
        put = httpx.put(target.json()["url"], content=data, headers=target.json()["headers"])
        assert put.status_code == 200
        confirmed = confirm(client, target.json()["upload_id"]).json()
        with psycopg.connect(migrated_url) as conn:
            row = conn.execute(
                "SELECT media_object_id FROM content.contents WHERE id = %s", [confirmed["id"]]
            ).fetchone()
        assert row is not None
        added = Added(
            confirmed["id"], str(row[0]), target.json()["upload_id"], key_of(target.json())
        )

        run_job(migrated_url, added)

        played = client.get(f"/api/v1/media/{added.media_id}", follow_redirects=False)
        assert played.status_code == 307
        url = played.headers["location"]
        # Seeking: storage answers a range request with just those bytes.
        part = httpx.get(url, headers={"Range": "bytes=1000-1999"})
        assert part.status_code == 206
        assert len(part.content) == 1000
        assert part.headers["content-type"] == "audio/mp4"
        assert httpx.get(url.split("?", 1)[0]).status_code == 403  # never public
        # The original is gone from the bucket.
        assert httpx.get(real.signed_download(added.source_key).url).status_code == 404
    finally:
        jobs.use_storage(None)
