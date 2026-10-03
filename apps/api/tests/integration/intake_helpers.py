"""Shared pieces of the intake and library tests: a fake storage and API helpers."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
import psycopg
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.platform.config import Settings
from listenup.platform.storage import SignedUrl, StoredObject
from tests.integration.conftest import with_csrf

MB = 1024 * 1024
PASSWORD = "correct horse battery"

ClientFactory = Callable[..., TestClient]


class FakeStorage:
    """In-memory storage: signs nothing real, remembers which objects 'arrived'."""

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.signed: list[tuple[str, str, int | None]] = []
        self.deleted: list[str] = []

    def signed_upload(
        self, key: str, content_type: str, content_length: int | None = None
    ) -> SignedUrl:
        self.signed.append((key, content_type, content_length))
        return SignedUrl(
            f"http://storage.test/bucket/{key}?X-Amz-Signature=fake",
            "PUT",
            datetime.now(UTC).timestamp() + 300,
            {"Content-Type": content_type},
        )

    def signed_download(self, key: str, download_name: str | None = None) -> SignedUrl:
        return SignedUrl(f"http://storage.test/bucket/{key}?sig", "GET", 0, {})

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = StoredObject(len(data), content_type)

    async def head(self, key: str) -> StoredObject | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self.objects if k.startswith(prefix)]
        for key in keys:
            del self.objects[key]
        return len(keys)

    def arrive(self, key: str, size: int, content_type: str = "audio/mpeg") -> None:
        """The browser's PUT reached storage."""
        self.objects[key] = StoredObject(size, content_type)


def client_factory(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    """Signed-in clients of a fresh app each; `fake=False` keeps the real S3 storage."""
    opened: list[TestClient] = []

    def make(fake: bool = True, **settings: object) -> TestClient:
        app = create_app(Settings(database_url=api_role_url, log_json=False, **settings))  # type: ignore[arg-type]
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        if fake:
            app.state.uploads.storage = storage
        opened.append(client)
        with_csrf(client)
        email = f"learner-{uuid.uuid4().hex}@example.com"
        registered = client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
        )
        assert registered.status_code == 201
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def learner_id(client: TestClient) -> str:
    return str(client.get("/api/v1/me").json()["id"])


def start(
    client: TestClient,
    filename: str = "street-trees-talk.mp3",
    content_type: str = "audio/mpeg",
    size: int = 50 * MB,
) -> httpx.Response:
    return client.post(
        "/api/v1/uploads",
        json={"filename": filename, "content_type": content_type, "size_bytes": size},
    )


def key_of(target: dict[str, object]) -> str:
    path = urlparse(str(target["url"])).path
    return path.split("/", 2)[2]  # /<bucket>/<key>


def confirm(
    client: TestClient, upload_id: object, key: str | None = None, **body: object
) -> httpx.Response:
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        "/api/v1/contents", json={"upload_id": str(upload_id), **body}, headers=headers
    )


def add_items(migrated_url: str, user: str, count: int, at: datetime | None = None) -> list[str]:
    """Items created one second apart (or all at `at`), oldest first; returns their ids."""
    ids: list[str] = []
    base = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    with psycopg.connect(migrated_url) as conn:
        for n in range(count):
            media_id, content_id = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                "INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by) "
                "VALUES (%s, %s, 'upload', %s)",
                [media_id, f"upload:{user}:{media_id}", user],
            )
            conn.execute(
                "INSERT INTO content.contents (id, user_id, media_object_id, title, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                [content_id, user, media_id, f"Clip {n}", at or base + timedelta(seconds=n)],
            )
            ids.append(str(content_id))
    return ids
