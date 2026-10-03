"""Upload a file straight to storage and confirm it (#35: FR-CI-1, FR-CI-3, FR-CI-6,
NFR-SEC-2, D5).

The app connects as a role with only the API's rights, so row-level security is in
force exactly as in production. Most tests swap storage for an in-memory fake that
satisfies the `Storage` protocol, so the intake rules run without an S3 server; the
tests at the end use a real bucket and are skipped when no S3 server is reachable,
unless LISTENUP_REQUIRE_S3=1 (as in CI).
"""

import os
import uuid
from collections.abc import Iterator

import boto3
import httpx
import psycopg
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient

from listenup.platform.config import Settings
from listenup.platform.storage import S3Storage
from tests.integration.intake_helpers import (
    MB,
    ClientFactory,
    FakeStorage,
    add_items,
    client_factory,
    confirm,
    key_of,
    learner_id,
    start,
)


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def upload_rows(migrated_url: str, user: str) -> list[tuple[object, ...]]:
    with psycopg.connect(migrated_url) as conn:
        return conn.execute(
            "SELECT storage_key, size_bytes, confirmed_at FROM content.uploads WHERE user_id = %s",
            [user],
        ).fetchall()


# --- Starting an upload: checks before any byte is sent ---------------------------------


def test_a_50_mb_file_is_declared_confirmed_and_listed(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    user = learner_id(client)

    started = start(client)

    assert started.status_code == 201
    target = started.json()
    assert target["method"] == "PUT"
    assert target["headers"] == {"Content-Type": "audio/mpeg"}
    key = key_of(target)
    assert key.startswith(f"users/{user}/uploads/") and key.endswith(".mp3")
    # The signature binds the exact declared size.
    assert storage.signed[-1] == (key, "audio/mpeg", 50 * MB)

    storage.arrive(key, 50 * MB)
    confirmed = confirm(client, target["upload_id"])

    assert confirmed.status_code == 201
    item = confirmed.json()
    assert item["title"] == "street-trees-talk"
    assert item["source"] == "upload"
    assert item["status"] == "pending"
    assert item["duration_ms"] is None

    listed = client.get("/api/v1/contents").json()
    assert [i["id"] for i in listed["items"]] == [item["id"]]

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT m.fingerprint, m.uploaded_by, m.ref_count FROM content.media_objects m "
            "JOIN content.contents c ON c.media_object_id = m.id WHERE c.id = %s",
            [item["id"]],
        ).fetchone()
        assert row is not None
        fingerprint, uploaded_by, ref_count = row
        assert fingerprint == f"upload:{user}:pending:{target['upload_id']}"
        assert str(uploaded_by) == user
        assert ref_count == 1
        jobs = conn.execute(
            "SELECT args FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'content.convert_upload' AND args->>'upload_id' = %s",
            [target["upload_id"]],
        ).fetchall()
        assert len(jobs) == 1


def test_a_file_over_500_mb_is_refused_before_any_bytes_are_sent(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    refused = start(client, size=500 * MB + 1)

    assert refused.status_code == 422
    assert refused.json()["code"] == "file_too_large"
    assert storage.signed == []
    assert upload_rows(migrated_url, learner_id(client)) == []
    assert start(client, size=500 * MB).status_code == 201


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.pdf", "application/pdf"),
        ("talk.mp3", "video/quicktime"),
        ("movie.mkv", "video/x-matroska"),
    ],
)
def test_an_unsupported_type_is_refused(
    client: TestClient, storage: FakeStorage, filename: str, content_type: str
) -> None:
    refused = start(client, filename=filename, content_type=content_type)

    assert refused.status_code == 422
    assert refused.json()["code"] == "unsupported_file_type"
    assert storage.signed == []


def test_uploads_that_would_pass_the_account_cap_are_refused(
    make_client: ClientFactory,
) -> None:
    client = make_client(upload_quota_bytes=100 * MB)

    assert start(client, size=60 * MB).status_code == 201
    refused = start(client, size=60 * MB)

    assert refused.status_code == 422
    assert refused.json()["code"] == "storage_full"
    assert refused.json()["used_bytes"] == 60 * MB
    usage = client.get("/api/v1/uploads/usage").json()
    assert usage == {
        "used_bytes": 60 * MB,
        "quota_bytes": 100 * MB,
        "max_file_bytes": 500 * MB,
    }


def test_uploads_are_rate_limited_per_learner(make_client: ClientFactory) -> None:
    client = make_client(upload_rate_limit=2)

    assert start(client).status_code == 201
    assert start(client).status_code == 201
    limited = start(client)

    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert "Retry-After" in limited.headers


def test_starting_an_upload_needs_a_signed_in_learner(client: TestClient) -> None:
    client.post("/api/v1/auth/logout")
    assert start(client).status_code == 401


# --- Confirming ---------------------------------------------------------------------------


def test_confirming_without_the_object_is_refused(client: TestClient) -> None:
    target = start(client).json()

    refused = confirm(client, target["upload_id"])

    assert refused.status_code == 409
    assert refused.json()["code"] == "upload_incomplete"
    assert client.get("/api/v1/contents").json()["items"] == []


def test_confirming_a_file_of_another_size_is_refused_and_the_object_removed(
    client: TestClient, storage: FakeStorage
) -> None:
    target = start(client).json()
    key = key_of(target)
    storage.arrive(key, 50 * MB + 1)

    refused = confirm(client, target["upload_id"])

    assert refused.status_code == 409
    assert refused.json()["code"] == "upload_size_mismatch"
    assert key in storage.deleted
    assert client.get("/api/v1/contents").json()["items"] == []


def test_confirming_an_unknown_upload_is_refused(client: TestClient) -> None:
    refused = confirm(client, uuid.uuid4())
    assert refused.status_code == 404
    assert refused.json()["code"] == "upload_not_found"


def test_confirming_an_expired_upload_is_refused(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    target = start(client).json()
    storage.arrive(key_of(target), 50 * MB)
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE content.uploads SET created_at = now() - interval '25 hours' WHERE id = %s",
            [target["upload_id"]],
        )

    refused = confirm(client, target["upload_id"])

    assert refused.status_code == 409
    assert refused.json()["code"] == "upload_expired"


def test_another_learner_cannot_confirm_my_upload_or_see_my_items(
    make_client: ClientFactory, storage: FakeStorage
) -> None:
    mine, theirs = make_client(), make_client()
    target = start(mine).json()
    storage.arrive(key_of(target), 50 * MB)

    stolen = confirm(theirs, target["upload_id"])
    assert stolen.status_code == 404
    assert theirs.delete(f"/api/v1/uploads/{target['upload_id']}").status_code == 404

    assert confirm(mine, target["upload_id"]).status_code == 201
    assert theirs.get("/api/v1/contents").json()["items"] == []
    assert len(mine.get("/api/v1/contents").json()["items"]) == 1


def test_confirmation_is_idempotent(client: TestClient, storage: FakeStorage) -> None:
    target = start(client).json()
    storage.arrive(key_of(target), 50 * MB)

    first = confirm(client, target["upload_id"], key="confirm-1", title="Street trees")
    replay = confirm(client, target["upload_id"], key="confirm-1", title="Street trees")
    again = confirm(client, target["upload_id"])

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    # Without a key, a second confirmation returns the same item rather than a new one.
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert first.json()["title"] == "Street trees"
    assert len(client.get("/api/v1/contents").json()["items"]) == 1


def test_a_cancelled_upload_leaves_no_content_item(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    target = start(client).json()
    key = key_of(target)

    cancelled = client.delete(f"/api/v1/uploads/{target['upload_id']}")

    assert cancelled.status_code == 204
    assert key in storage.deleted
    assert upload_rows(migrated_url, learner_id(client)) == []
    assert confirm(client, target["upload_id"]).status_code == 404
    assert client.get("/api/v1/contents").json()["items"] == []
    # A cancelled upload no longer counts against the storage cap.
    assert client.get("/api/v1/uploads/usage").json()["used_bytes"] == 0


def test_a_confirmed_upload_cannot_be_cancelled(client: TestClient, storage: FakeStorage) -> None:
    target = start(client).json()
    storage.arrive(key_of(target), 50 * MB)
    confirm(client, target["upload_id"])

    refused = client.delete(f"/api/v1/uploads/{target['upload_id']}")

    assert refused.status_code == 409
    assert refused.json()["code"] == "upload_confirmed"


def test_my_items_page_as_20_then_10_newest_first(client: TestClient, migrated_url: str) -> None:
    ids = add_items(migrated_url, learner_id(client), 30)

    page1 = client.get("/api/v1/contents").json()
    page2 = client.get("/api/v1/contents", params={"cursor": page1["next_cursor"]}).json()

    assert [i["id"] for i in page1["items"]] == ids[::-1][:20]
    assert [i["id"] for i in page2["items"]] == ids[::-1][20:]
    assert page2["next_cursor"] is None


# --- A real S3 server ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def bucket() -> Iterator[str]:
    """A throwaway bucket on the S3 server; skips when none is reachable (test_storage.py)."""
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


def test_a_real_upload_is_private_bound_to_its_size_and_confirmed(
    make_client: ClientFactory, bucket: str
) -> None:
    client = make_client(fake=False, s3_bucket=bucket)
    user = learner_id(client)
    data = b"ID3" + os.urandom(64 * 1024)
    target = start(client, size=len(data)).json()
    key = key_of(target)
    assert key.startswith(f"users/{user}/uploads/")

    # Storage refuses a body of another size than the one declared.
    wrong = httpx.put(target["url"], content=data + b"x", headers=target["headers"])
    assert wrong.status_code == 403
    assert confirm(client, target["upload_id"]).json()["code"] == "upload_incomplete"

    put = httpx.put(target["url"], content=data, headers=target["headers"])
    assert put.status_code == 200

    # The bucket is not public: the object cannot be read without a signature.
    unsigned = target["url"].split("?", 1)[0]
    assert httpx.get(unsigned).status_code == 403

    confirmed = confirm(client, target["upload_id"])
    assert confirmed.status_code == 201
    assert confirmed.json()["status"] == "pending"


def test_a_real_cancelled_upload_removes_its_object(
    make_client: ClientFactory, bucket: str
) -> None:
    client = make_client(fake=False, s3_bucket=bucket)
    data = os.urandom(1024)
    target = start(client, size=len(data)).json()
    assert httpx.put(target["url"], content=data, headers=target["headers"]).status_code == 200

    assert client.delete(f"/api/v1/uploads/{target['upload_id']}").status_code == 204

    storage = S3Storage(Settings(s3_bucket=bucket))
    assert httpx.get(storage.signed_download(key_of(target)).url).status_code == 404
