"""Clear refusals for files that cannot be added (#39: FR-CI-3, NFR-USE-3, D5; ADR 0027).

Every refusal names what happened and what to do next. A copy of a clip the learner
already has is removed by the conversion job (ADR 0022); its page then says so and
links to the clip they have. The storage cap counts what uploads really keep in
storage. The API runs with only the API's rights; jobs run as the workers would.
"""

import asyncio
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.content import jobs
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import (
    MB,
    ClientFactory,
    FakeStorage,
    client_factory,
    confirm,
    key_of,
    start,
)


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


@pytest.fixture(scope="module")
def tone(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path: Path = tmp_path_factory.mktemp("messages") / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=330:duration=32", "-ac", "1", "-b:a", "64k", str(path)],
        check=True, timeout=60,
    )  # fmt: skip
    return path.read_bytes()


def add(
    client: TestClient, storage: FakeStorage, data: bytes, title: str | None = None
) -> dict[str, str]:
    target = start(client, filename="talk.mp3", size=len(data)).json()
    storage.arrive(key_of(target), len(data), "audio/mpeg", data)
    body = {"title": title} if title else {}
    confirmed = confirm(client, target["upload_id"], **body)
    assert confirmed.status_code == 201, confirmed.text
    content_id = confirmed.json()["id"]
    media_id = client.get(f"/api/v1/contents/{content_id}").json()["media_object_id"]
    return {"content_id": content_id, "upload_id": target["upload_id"], "media_id": media_id}


def run_job(migrated_url: str, item: dict[str, str]) -> None:
    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.convert_upload(
                JobDeps(database, None, 1),
                media_object_id=item["media_id"],
                upload_id=item["upload_id"],
            )
        finally:
            await database.dispose()

    asyncio.run(run())


# --- Refusals before any byte is sent ---------------------------------------------------


def test_an_unsupported_type_names_the_accepted_ones(client: TestClient) -> None:
    refused = start(client, filename="notes.pdf", content_type="application/pdf")

    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "notes.pdf is not a file type we accept. Choose an MP3, M4A, WAV, MP4, MOV or WEBM file."
    )


def test_a_file_over_the_limit_names_its_size_and_the_limit(client: TestClient) -> None:
    refused = start(client, size=501 * MB)

    assert refused.json()["code"] == "file_too_large"
    assert refused.json()["detail"] == (
        "street-trees-talk.mp3 is 501 MB. The limit is 500 MB per file. "
        "Cut the part you want to practise, then upload that."
    )


def test_a_full_account_says_how_much_is_used_and_what_to_do(
    make_client: ClientFactory,
) -> None:
    client = make_client(upload_quota_bytes=100 * MB)
    assert start(client, size=90 * MB).status_code == 201

    refused = start(client, size=20 * MB)

    assert refused.json()["code"] == "storage_full"
    assert refused.json()["detail"] == (
        "You have used 90 MB of 100 MB, and this file is 20 MB. "
        "Delete a clip you have finished to make room."
    )


# --- The same file twice ----------------------------------------------------------------


def test_a_removed_copy_says_you_already_have_this_clip_with_a_link(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    first = add(client, storage, tone, title="Morning news")
    run_job(migrated_url, first)
    second = add(client, storage, tone, title="Morning news again")

    run_job(migrated_url, second)

    removed = client.get(f"/api/v1/contents/{second['content_id']}")
    assert removed.status_code == 410
    problem = removed.json()
    assert problem["code"] == "duplicate_upload"
    assert problem["existing_content_id"] == first["content_id"]
    assert problem["existing_title"] == "Morning news"
    assert problem["detail"] == (
        "You already have this clip in your library, as “Morning news”, so this copy "
        "was not added. Open that clip to practise it."
    )


def test_another_learner_cannot_learn_about_my_removed_copy(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    mine, theirs = make_client(), make_client()
    run_job(migrated_url, add(mine, storage, tone))
    second = add(mine, storage, tone)
    run_job(migrated_url, second)

    seen = theirs.get(f"/api/v1/contents/{second['content_id']}")

    assert seen.status_code == 404
    assert seen.json()["code"] == "content_not_found"
    assert "existing_content_id" not in seen.json()


def test_once_the_kept_clip_is_deleted_the_copy_is_simply_gone(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    first = add(client, storage, tone)
    run_job(migrated_url, first)
    second = add(client, storage, tone)
    run_job(migrated_url, second)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM content.contents WHERE id = %s", [first["content_id"]])

    assert client.get(f"/api/v1/contents/{second['content_id']}").status_code == 404


# --- What the storage cap counts --------------------------------------------------------


def test_the_cap_counts_what_is_stored_after_conversion(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    item = add(client, storage, tone)
    assert client.get("/api/v1/uploads/usage").json()["used_bytes"] == len(tone)

    run_job(migrated_url, item)

    playback = storage.data[
        next(key for key in storage.data if key.endswith(f"{item['media_id']}/playback.mp4"))
    ]
    assert client.get("/api/v1/uploads/usage").json()["used_bytes"] == len(playback)


def test_a_failed_clip_takes_no_storage(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    item = add(client, storage, b"Not audio at all.\n" * 100)

    with pytest.raises(PermanentError):
        run_job(migrated_url, item)

    assert client.get("/api/v1/uploads/usage").json()["used_bytes"] == 0
    detail = client.get(f"/api/v1/contents/{item['content_id']}").json()
    assert detail["error_code"] == "unsupported_media"
    assert detail["error_detail"].startswith("This file isn't audio or video we can play")
