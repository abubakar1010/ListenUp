"""List my content in the library (#44: FR-LB-1, FR-ACC-2, AT-8 partial).

The app connects as a role with only the API's rights, so row-level security is in
force exactly as in production. Storage is an in-memory fake; nothing here needs S3.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.platform.config import Settings
from tests.integration.conftest import with_csrf
from tests.integration.intake_helpers import (
    MB,
    PASSWORD,
    ClientFactory,
    FakeStorage,
    add_items,
    client_factory,
    confirm,
    key_of,
    learner_id,
    start,
)

LIBRARY = "/api/v1/library/contents"


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def test_an_uploaded_clip_appears_in_the_library_as_pending(
    client: TestClient, storage: FakeStorage
) -> None:
    target = start(client).json()
    storage.arrive(key_of(target), 50 * MB)
    item = confirm(client, target["upload_id"]).json()

    library = client.get(LIBRARY)

    assert library.status_code == 200
    assert library.json() == {
        "items": [
            {
                "id": item["id"],
                "title": "street-trees-talk",
                "source": "upload",
                "status": "pending",
                "duration_ms": None,
                "created_at": item["created_at"],
                "last_session_status": None,
            }
        ],
        "next_cursor": None,
    }


def test_30_items_page_as_20_then_10_newest_first(client: TestClient, migrated_url: str) -> None:
    ids = add_items(migrated_url, learner_id(client), 30)

    page1 = client.get(LIBRARY).json()
    page2 = client.get(LIBRARY, params={"cursor": page1["next_cursor"]}).json()

    assert [i["id"] for i in page1["items"]] == ids[::-1][:20]
    assert page1["items"][0]["title"] == "Clip 29"
    assert [i["id"] for i in page2["items"]] == ids[::-1][20:]
    assert page2["next_cursor"] is None


def test_items_created_at_the_same_moment_page_without_gaps(
    client: TestClient, migrated_url: str
) -> None:
    ids = add_items(migrated_url, learner_id(client), 5, at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC))

    seen: list[str] = []
    params: dict[str, object] = {"limit": 2}
    while True:
        page = client.get(LIBRARY, params=params).json()
        seen += [i["id"] for i in page["items"]]
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]

    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen))


def test_a_broken_cursor_is_refused(client: TestClient) -> None:
    refused = client.get(LIBRARY, params={"cursor": "nonsense"})
    assert refused.status_code == 400
    assert refused.json()["code"] == "invalid_cursor"


def test_another_learner_never_sees_my_items(make_client: ClientFactory, migrated_url: str) -> None:
    mine, theirs = make_client(), make_client()
    add_items(migrated_url, learner_id(mine), 3)

    assert theirs.get(LIBRARY).json()["items"] == []
    assert len(mine.get(LIBRARY).json()["items"]) == 3


def test_an_unchanged_library_page_answers_304(client: TestClient, migrated_url: str) -> None:
    add_items(migrated_url, learner_id(client), 2)
    etag = client.get(LIBRARY).headers["ETag"]

    unchanged = client.get(LIBRARY, headers={"If-None-Match": etag})
    assert unchanged.status_code == 304

    add_items(migrated_url, learner_id(client), 1)
    changed = client.get(LIBRARY, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert len(changed.json()["items"]) == 3


def test_the_same_library_appears_from_a_second_browser(
    client: TestClient, api_role_url: str, migrated_url: str
) -> None:
    """AT-8 (partial): the library follows the account, not the browser."""
    ids = add_items(migrated_url, learner_id(client), 3)
    email = client.get("/api/v1/me").json()["email"]

    app = create_app(Settings(database_url=api_role_url, log_json=False))
    with TestClient(app) as second:
        with_csrf(second)
        signed_in = second.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert signed_in.status_code == 200
        items = second.get(LIBRARY).json()["items"]
    assert [i["id"] for i in items] == ids[::-1]


def test_the_library_needs_a_signed_in_learner(client: TestClient) -> None:
    client.post("/api/v1/auth/logout")
    assert client.get(LIBRARY).status_code == 401
