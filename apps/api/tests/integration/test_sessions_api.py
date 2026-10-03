"""The sessions API (#48: start a plan and show progress; #49: entry change and skips).

The app connects as a role with only the API's rights, so row-level security is in
force as in production. Content items are inserted directly, ready or not, so nothing
here needs S3. Mode steps have no endpoints yet, so tests finish them through the
practice service, as a mode endpoint will.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
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


def change_entry(client: TestClient, session: dict[str, object], entry: str) -> httpx.Response:
    return client.patch(
        f"{SESSIONS}/{session['id']}/entry", json={"entry": entry, "version": session["version"]}
    )


def skip(
    client: TestClient, session: dict[str, object], step: str, confirmed: bool = True
) -> httpx.Response:
    return client.post(
        f"{SESSIONS}/{session['id']}/steps/{step}/skip",
        json={"confirmed": confirmed, "version": session["version"]},
    )


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

    for response in (
        theirs.get(f"{SESSIONS}/{session['id']}"),
        change_entry(theirs, session, "both"),
        skip(theirs, session, "card"),
    ):
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


# Changing the entry (#49)


def test_changing_blind_to_both_before_transcript_gives_5_steps(
    client: TestClient, clip: str
) -> None:
    """AT-7 (part): "Step 1 of 4" becomes "Step 1 of 5"."""
    session = start(client, clip, "blind")

    changed = change_entry(client, session, "both")

    assert changed.status_code == 200
    body = changed.json()
    assert body["entry"] == "both"
    assert body["step_count"] == 5
    assert body["open_position"] == 1
    assert body["version"] == session["version"] + 1  # type: ignore[operator]
    assert load(client, session) == body


def test_the_entry_locks_once_transcript_opens(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    session = load(client, start(client, clip, "blind"))
    finish(api_role_url, client, session["id"], Step.BLIND)
    session = load(client, session)
    assert session["open_step"] == "transcript"
    assert session["entry_locked"] is True

    # Transcript opened when Blind finished, so the entry is locked now.
    refused = change_entry(client, session, "both")

    assert refused.status_code == 409
    assert refused.json()["code"] == "entry_locked"
    assert load(client, session) == session


def test_dropping_dictation_after_blind_is_done_keeps_blind(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    session = start(client, clip, "both")
    finish(api_role_url, client, session["id"], Step.BLIND)
    session = load(client, session)

    changed = change_entry(client, session, "blind").json()

    assert steps_of(changed) == [
        ("blind", 1, "done"),
        ("transcript", 2, "open"),
        ("card", 3, "locked"),
        ("shadow", 4, "locked"),
    ]
    assert changed["entry_locked"] is True


def test_removing_a_finished_entry_exercise_is_refused(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    session = start(client, clip, "both")
    finish(api_role_url, client, session["id"], Step.BLIND)
    session = load(client, session)

    refused = change_entry(client, session, "dictation")

    assert refused.status_code == 409
    assert refused.json()["code"] == "entry_locked"


def test_a_stale_version_is_refused(client: TestClient, clip: str) -> None:
    session = start(client, clip, "blind")
    assert change_entry(client, session, "both").status_code == 200

    # The page still shows version 0.
    stale_entry = change_entry(client, session, "dictation")
    stale_skip = skip(client, session, "card")

    for response in (stale_entry, stale_skip):
        assert response.status_code == 409
        assert response.json()["code"] == "session_changed"
    assert load(client, session)["entry"] == "both"


# Skipping (#49)


def at_card(client: TestClient, clip: str, api_role_url: str) -> dict[str, object]:
    session = start(client, clip, "blind")
    finish(api_role_url, client, session["id"], Step.BLIND, Step.TRANSCRIPT)
    return load(client, session)


def test_transcript_cannot_be_skipped(client: TestClient, clip: str, api_role_url: str) -> None:
    session = start(client, clip, "dictation")
    finish(api_role_url, client, session["id"], Step.DICTATION)
    session = load(client, session)

    refused = skip(client, session, "transcript")

    assert refused.status_code == 409
    assert refused.json()["code"] == "step_not_skippable"
    assert load(client, session)["open_step"] == "transcript"


@pytest.mark.parametrize("step", ["blind", "dictation"])
def test_entry_exercises_cannot_be_skipped(client: TestClient, clip: str, step: str) -> None:
    session = start(client, clip, "both")
    refused = skip(client, session, step)
    assert refused.status_code == 409
    assert refused.json()["code"] == "step_not_skippable"


def test_skipping_card_needs_confirmation(client: TestClient, clip: str, api_role_url: str) -> None:
    session = at_card(client, clip, api_role_url)

    unconfirmed = skip(client, session, "card", confirmed=False)

    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["code"] == "confirmation_required"
    assert load(client, session) == session

    skipped = skip(client, session, "card").json()
    assert steps_of(skipped)[2:] == [("card", 3, "skipped"), ("shadow", 4, "open")]
    assert skipped["open_position"] == 4
    assert skipped["status"] == "active"


def test_a_locked_step_cannot_be_skipped_early(client: TestClient, clip: str) -> None:
    session = start(client, clip, "blind")
    refused = skip(client, session, "card")
    assert refused.status_code == 409
    assert refused.json()["code"] == "step_locked"


def test_skipping_shadow_after_card_was_done_completes_the_session(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    """D12, SR-6: Shadow skipped completes the session, whatever happened to Card."""
    session = at_card(client, clip, api_role_url)
    finish(api_role_url, client, session["id"], Step.CARD)
    session = load(client, session)

    unconfirmed = skip(client, session, "shadow", confirmed=False)
    assert unconfirmed.json()["code"] == "confirmation_required"

    done = skip(client, session, "shadow").json()

    assert done["status"] == "completed"
    assert done["completed_at"] is not None
    assert done["open_step"] is None
    assert done["open_position"] is None
    assert steps_of(done)[-2:] == [("card", 3, "done"), ("shadow", 4, "skipped")]
    closed = skip(client, done, "shadow")
    assert closed.json()["code"] == "session_closed"


def test_skipping_card_then_shadow_completes_the_session(
    client: TestClient, clip: str, api_role_url: str
) -> None:
    session = at_card(client, clip, api_role_url)
    after_card = skip(client, session, "card").json()
    done = skip(client, after_card, "shadow").json()
    assert done["status"] == "completed"
