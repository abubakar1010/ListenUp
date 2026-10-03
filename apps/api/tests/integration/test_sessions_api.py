"""The sessions API (#48: start a plan and show progress).

The app connects as a role with only the API's rights, so row-level security is in
force as in production. Content items are inserted directly, ready or not, so nothing
here needs S3. Mode steps have no endpoints yet, so tests finish them through the
practice service, as a mode endpoint will.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.practice import service
from listenup.modules.practice.service import Step
from listenup.platform.database import Database
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)

SESSIONS = "/api/v1/sessions"
TWO_MINUTES = {"start_ms": 0, "end_ms": 120_000}


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, FakeStorage())


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def add_clip(
    url: str,
    user: str,
    *,
    status: str = "playable",
    duration_ms: int | None = 600_000,
    title: str = "Why cities plant street trees",
) -> str:
    media_id, content_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.media_objects "
            "(id, fingerprint, source, uploaded_by, status, duration_ms) "
            "VALUES (%s, %s, 'upload', %s, %s, %s)",
            [media_id, f"upload:{user}:{media_id}", user, status, duration_ms],
        )
        conn.execute(
            "INSERT INTO content.contents (id, user_id, media_object_id, title) "
            "VALUES (%s, %s, %s, %s)",
            [content_id, user, media_id, title],
        )
    return str(content_id)


@pytest.fixture
def clip(client: TestClient, migrated_url: str) -> str:
    return add_clip(migrated_url, learner_id(client))


def start(
    client: TestClient,
    content_id: str,
    entry: str = "blind",
    passage: dict[str, int] | None = None,
    key: str | None = None,
) -> dict[str, object]:
    response = client.post(
        SESSIONS,
        json={"content_id": content_id, "passage": passage or TWO_MINUTES, "entry": entry},
        headers={"Idempotency-Key": key} if key else {},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def finish(api_role_url: str, client: TestClient, session_id: object, *steps: Step) -> None:
    """Finish steps as their mode endpoints will: require_step, then complete_step."""

    async def run() -> None:
        database = Database(api_role_url, pool_size=1)
        learner = uuid.UUID(learner_id(client))
        try:
            for step in steps:
                async with database.transaction(learner) as db:
                    practice = await service.require_step(db, uuid.UUID(str(session_id)), step)
                    await service.complete_step(db, practice, step)
        finally:
            await database.dispose()

    asyncio.run(run())


def steps_of(session: dict[str, object]) -> list[tuple[str, int, str]]:
    return [(s["step"], s["position"], s["status"]) for s in session["steps"]]


def load(client: TestClient, session: dict[str, object]) -> dict[str, object]:
    response = client.get(f"{SESSIONS}/{session['id']}")
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


# Starting a plan (#48)


@pytest.mark.parametrize(
    ("entry", "path"),
    [
        ("blind", ["blind", "transcript", "card", "shadow"]),
        ("dictation", ["dictation", "transcript", "card", "shadow"]),
        ("both", ["blind", "dictation", "transcript", "card", "shadow"]),
    ],
)
def test_the_entry_choice_gives_a_plan_of_4_or_5_steps(
    client: TestClient, clip: str, entry: str, path: list[str]
) -> None:
    """AT-7 (part): Blind 4 steps, Dictation 4, both 5, in the order of FR-PL-2."""
    session = start(client, clip, entry)

    assert steps_of(session) == [
        (step, n, "open" if n == 1 else "locked") for n, step in enumerate(path, start=1)
    ]
    assert session["step_count"] == len(path)
    assert session["open_step"] == path[0]
    assert session["open_position"] == 1
    assert session["status"] == "active"
    assert session["entry"] == entry
    assert session["entry_locked"] is False
    assert session["content_id"] == clip
    assert session["content_title"] == "Why cities plant street trees"
    assert session["passage"] == TWO_MINUTES
    assert load(client, session) == session


def test_progress_follows_finished_steps(client: TestClient, clip: str, api_role_url: str) -> None:
    session = start(client, clip, "both")
    finish(api_role_url, client, session["id"], Step.BLIND)

    progress = load(client, session)

    assert progress["open_step"] == "dictation"
    assert progress["open_position"] == 2
    assert progress["step_count"] == 5
    assert steps_of(progress)[0] == ("blind", 1, "done")
    assert progress["version"] == 1


def test_a_second_plan_starts_on_the_same_clip(client: TestClient, clip: str) -> None:
    """FR-LB-2: a new plan on content already in the library, without adding it again."""
    first = start(client, clip, "blind")
    second = start(client, clip, "dictation")

    assert first["id"] != second["id"]
    assert first["content_id"] == second["content_id"] == clip


def test_the_same_idempotency_key_starts_one_session(client: TestClient, clip: str) -> None:
    first = start(client, clip, key="start-1")
    again = client.post(
        SESSIONS,
        json={"content_id": clip, "passage": TWO_MINUTES, "entry": "blind"},
        headers={"Idempotency-Key": "start-1"},
    )

    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first["id"]
    assert len(client.get(SESSIONS).json()["items"]) == 1


@pytest.mark.parametrize("status", ["pending", "downloading", "failed", "expired"])
def test_a_clip_that_cannot_play_yet_is_refused(
    client: TestClient, migrated_url: str, status: str
) -> None:
    clip = add_clip(migrated_url, learner_id(client), status=status, duration_ms=None)

    refused = client.post(
        SESSIONS, json={"content_id": clip, "passage": TWO_MINUTES, "entry": "blind"}
    )

    assert refused.status_code == 409
    assert refused.json()["code"] == "content_not_ready"
    assert refused.json()["content_status"] == status
    assert client.get(SESSIONS).json()["items"] == []


@pytest.mark.parametrize(
    ("passage", "code"),
    [
        ({"start_ms": 0, "end_ms": 29_999}, "invalid_passage"),
        ({"start_ms": 0, "end_ms": 900_001}, "invalid_passage"),
        ({"start_ms": 60_000, "end_ms": 30_000}, "invalid_passage"),
        ({"start_ms": 0, "end_ms": 900_000}, "passage_outside_clip"),
        ({"start_ms": 590_000, "end_ms": 620_000}, "passage_outside_clip"),
    ],
)
def test_a_passage_must_be_30_s_to_15_min_and_inside_the_clip(
    client: TestClient, clip: str, passage: dict[str, int], code: str
) -> None:
    """C2: 30 s to 15 min. The clip is 10 minutes long."""
    refused = client.post(SESSIONS, json={"content_id": clip, "passage": passage, "entry": "both"})

    assert refused.status_code == 422
    assert refused.json()["code"] == code


def test_the_whole_clip_is_a_valid_passage(client: TestClient, clip: str) -> None:
    session = start(client, clip, passage={"start_ms": 0, "end_ms": 600_000})
    assert session["passage"] == {"start_ms": 0, "end_ms": 600_000}


def test_a_clip_under_30_s_cannot_start_a_plan(client: TestClient, migrated_url: str) -> None:
    clip = add_clip(migrated_url, learner_id(client), duration_ms=20_000)
    refused = client.post(
        SESSIONS,
        json={"content_id": clip, "passage": {"start_ms": 0, "end_ms": 30_000}, "entry": "blind"},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "clip_too_short"


def test_unknown_content_is_not_found(client: TestClient) -> None:
    refused = client.post(
        SESSIONS, json={"content_id": str(uuid.uuid4()), "passage": TWO_MINUTES, "entry": "blind"}
    )
    assert refused.status_code == 404
    assert refused.json()["code"] == "content_not_found"


def test_another_learner_can_neither_see_nor_use_my_sessions(
    make_client: ClientFactory, migrated_url: str
) -> None:
    mine, theirs = make_client(), make_client()
    clip = add_clip(migrated_url, learner_id(mine))
    session = start(mine, clip)

    response = theirs.get(f"{SESSIONS}/{session['id']}")
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
    started = theirs.post(
        SESSIONS, json={"content_id": clip, "passage": TWO_MINUTES, "entry": "blind"}
    )
    assert started.status_code == 404
    assert started.json()["code"] == "content_not_found"
    assert theirs.get(SESSIONS).json()["items"] == []
    assert load(mine, session)["version"] == 0


def test_a_missing_session_is_not_found(client: TestClient) -> None:
    response = client.get(f"{SESSIONS}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


# The sessions list


def test_sessions_list_most_recently_active_first(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    older = start(client, clip)
    newer = start(client, clip, "dictation")
    finish(api_role_url, client, older["id"], Step.BLIND)  # older is now the most recent

    items = client.get(SESSIONS).json()["items"]

    assert [i["id"] for i in items] == [older["id"], newer["id"]]
    assert items[0]["open_step"] == "transcript"
    assert items[0]["content_title"] == "Why cities plant street trees"


def test_sessions_page_by_keyset_without_gaps(
    client: TestClient, clip: str, migrated_url: str
) -> None:
    ids = [str(start(client, clip)["id"]) for _ in range(5)]
    # Two share one moment, so the id breaks the tie.
    base = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    moments = [base, base + timedelta(seconds=1), base + timedelta(seconds=1)]
    moments += [base + timedelta(seconds=2), base + timedelta(seconds=3)]
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("ALTER TABLE practice.sessions DISABLE TRIGGER sessions_touch")
        try:
            for session_id, moment in zip(ids, moments, strict=True):
                conn.execute(
                    "UPDATE practice.sessions SET updated_at = %s WHERE id = %s",
                    [moment, session_id],
                )
        finally:
            conn.execute("ALTER TABLE practice.sessions ENABLE TRIGGER sessions_touch")

    seen: list[str] = []
    params: dict[str, object] = {"limit": 2}
    pages = 0
    while True:
        page = client.get(SESSIONS, params=params).json()
        pages += 1
        seen += [i["id"] for i in page["items"]]
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]

    assert pages == 3
    assert seen[0] == ids[4] and seen[1] == ids[3] and seen[4] == ids[0]
    assert sorted(seen[2:4]) == sorted(ids[1:3])
    assert len(set(seen)) == 5


def test_a_broken_cursor_is_refused(client: TestClient) -> None:
    refused = client.get(SESSIONS, params={"cursor": "nonsense"})
    assert refused.status_code == 400
    assert refused.json()["code"] == "invalid_cursor"
