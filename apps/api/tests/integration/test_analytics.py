"""Product analytics events and the success-metrics report (#101, PRD 2 and 8.2, ADR 0034).

The app connects as the API role, so row-level security applies and the role may only
insert events. Events are read back as the migration owner. Mode steps without
endpoints are finished through the practice service, as their endpoints will.

Acceptance criteria:
- AC1, each event once per occurrence: the API flows below, plus the recording
  functions that marks, cards, Shadow and Dictation submission will call.
- AC2, the report: `test_the_report_*`, run as `listenup_readonly`.
- AC3, removed on account deletion: `test_deleting_the_account_removes_its_events`
  (the purge in #91 deletes the `identity.users` row); the export side is in
  test_export.py.
"""

import asyncio
import importlib.util
import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.blind import jobs as blind_jobs
from listenup.modules.blind import service as blind_service
from listenup.modules.blind.domain import MAX_SILENCE_MS, Beat, Interruption, PlayerState
from listenup.modules.practice.service import Step
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import (
    MB,
    ClientFactory,
    FakeStorage,
    client_factory,
    confirm,
    key_of,
    learner_id,
    start,
)
from tests.integration.test_blind import (
    END,
    PASSAGE,
    SENTENCES_3,
    START,
    Clock,
    add_clip,
    attempt_id,
    beat,
    play,
    start_attempt,
    with_clock,
)
from tests.integration.test_sessions_api import change_entry, finish, load, skip

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analytics_report.py"

Recorded = tuple[str, str | None, dict[str, Any]]


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(make_client: ClientFactory, clock: Clock) -> TestClient:
    return with_clock(make_client(), clock)


def events_of(url: str, learner: object, kind: str | None = None) -> list[Recorded]:
    """(event type, step, properties) of a learner's events, oldest first.

    Events of one transaction share `occurred_at`; they are ordered by type and step.
    """
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT event_type, step, properties FROM ops.analytics_events "
            "WHERE user_id = %s AND (%s::text IS NULL OR event_type = %s) "
            "ORDER BY occurred_at, event_type, step",
            [learner, kind, kind],
        ).fetchall()
    return [(str(r[0]), r[1], dict(r[2])) for r in rows]


def kinds(events: list[Recorded]) -> Counter[tuple[str, str | None]]:
    return Counter((kind, step) for kind, step, _ in events)


def new_session(client: TestClient, url: str, entry: str = "blind") -> str:
    content_id, _ = add_clip(url, learner_id(client))
    response = client.post(
        "/api/v1/sessions",
        json={"content_id": content_id, "passage": PASSAGE, "entry": entry},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def in_transaction(
    url: str, learner: uuid.UUID, work: Callable[[AsyncSession], Awaitable[object]]
) -> None:
    async def run() -> None:
        database = Database(url, pool_size=1)
        try:
            async with database.transaction(learner) as db:
                await work(db)
        finally:
            await database.dispose()

    asyncio.run(run())


# -- AC1: each event once per occurrence ------------------------------------------------


def test_a_confirmed_upload_records_content_added_once(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    target = start(client).json()
    storage.arrive(key_of(target), 50 * MB)

    first = confirm(client, target["upload_id"], key="confirm-1")
    confirm(client, target["upload_id"], key="confirm-1")  # replayed by its key
    confirm(client, target["upload_id"])  # confirmed again: the same item

    assert first.status_code == 201
    assert events_of(migrated_url, learner_id(client)) == [
        ("content_added", None, {"source_type": "upload"})
    ]


def test_a_refused_confirmation_records_nothing(client: TestClient, migrated_url: str) -> None:
    target = start(client).json()  # the file never reached storage

    assert confirm(client, target["upload_id"]).status_code == 409
    assert events_of(migrated_url, learner_id(client)) == []


def test_starting_a_plan_records_its_path_and_first_step_once(
    client: TestClient, migrated_url: str
) -> None:
    content_id, _ = add_clip(migrated_url, learner_id(client))
    body = {"content_id": content_id, "passage": PASSAGE, "entry": "both"}
    headers = {"Idempotency-Key": "plan-1"}
    first = client.post("/api/v1/sessions", json=body, headers=headers)
    response = client.post("/api/v1/sessions", json=body, headers=headers)  # replayed, not rerun

    assert first.status_code == 201
    assert response.headers.get("Idempotent-Replayed") == "true"
    assert events_of(migrated_url, learner_id(client)) == [
        ("plan_started", None, {"path": "both"}),
        ("step_started", "blind", {}),
    ]


def test_a_refused_plan_records_nothing(client: TestClient, migrated_url: str) -> None:
    content_id, _ = add_clip(migrated_url, learner_id(client))
    refused = client.post(
        "/api/v1/sessions",
        json={"content_id": content_id, "passage": {"start_ms": 0, "end_ms": 10}, "entry": "blind"},
    )

    assert refused.status_code == 422
    assert events_of(migrated_url, learner_id(client)) == []


def test_a_whole_blind_step_records_listen_completion_and_the_next_step(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, END)

    submitted = client.post(f"/api/v1/blind/attempts/{attempt}/gist", json={"text": SENTENCES_3})

    assert submitted.status_code == 201, submitted.text
    assert events_of(migrated_url, learner_id(client)) == [
        ("plan_started", None, {"path": "blind"}),
        ("step_started", "blind", {}),
        ("listen_started", None, {"mode": "blind"}),
        ("step_completed", "blind", {"outcome": "done"}),
        ("step_started", "transcript", {}),
    ]


def test_a_voided_blind_attempt_is_abandoned_once(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    first = attempt_id(start_attempt(client, session_id))
    for _ in range(2):  # a repeated report changes nothing
        client.post(f"/api/v1/blind/attempts/{first}/void", json={"reason": "left_page"})
    second = attempt_id(start_attempt(client, session_id))
    clock.advance(20_000)
    assert beat(client, second, START + 20_000)["action"] == "stop"  # missed heartbeats
    assert beat(client, second, START + 25_000)["action"] == "stop"  # already ended

    learner = learner_id(client)
    assert events_of(migrated_url, learner, "blind_abandoned") == [
        ("blind_abandoned", None, {"reason": "left_page"}),
        ("blind_abandoned", None, {"reason": "missed_heartbeat"}),
    ]
    assert len(events_of(migrated_url, learner, "listen_started")) == 2


def test_a_vanished_blind_browser_is_expired_and_recorded(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = uuid.UUID(attempt_id(start_attempt(client, session_id)))
    clock.advance(300_000)

    async def expire() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await blind_jobs.expire_attempt_job(JobDeps(database, None, 1), str(attempt))
            assert events_of(migrated_url, learner_id(client), "blind_abandoned") == [
                ("blind_abandoned", None, {"reason": "missed_heartbeat"})
            ]
            await blind_jobs.expire_attempt(database, attempt, clock.now)  # a job retry
        finally:
            await database.dispose()

    asyncio.run(expire())

    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == [
        ("blind_abandoned", None, {"reason": "missed_heartbeat"})
    ]
    stopped = client.post(
        f"/api/v1/blind/attempts/{attempt}/heartbeat",
        json={"position_ms": START, "state": "playing", "visible": True},
    )
    assert stopped.status_code == 200
    assert stopped.json()["action"] == "stop"


def test_a_recent_blind_heartbeat_moves_the_expiry_check(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = uuid.UUID(attempt_id(start_attempt(client, session_id)))
    clock.advance(5_000)
    assert beat(client, str(attempt), START + 5_000)["action"] == "continue"
    clock.advance(295_000)  # the original recovery deadline is due, the new one is not

    async def check() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await blind_jobs.expire_attempt(database, attempt, clock.now)
        finally:
            await database.dispose()

    asyncio.run(check())

    with psycopg.connect(migrated_url) as conn:
        status = conn.execute(
            "SELECT status FROM practice.attempts WHERE id = %s", [attempt]
        ).fetchone()
        queued = conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s AND args->>'attempt_id' = %s",
            [blind_jobs.EXPIRE_ATTEMPT, str(attempt)],
        ).fetchone()
    assert status == ("active",)
    assert queued == (2,)
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == []


def test_worker_preserves_first_network_recovery(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, START + 10_000)
    clock.advance(MAX_SILENCE_MS + 1)

    async def check() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await blind_jobs.expire_attempt(database, uuid.UUID(attempt), clock.now)
        finally:
            await database.dispose()

    asyncio.run(check())
    clock.advance(40_000 - MAX_SILENCE_MS - 1)
    answer = beat(client, attempt, START + 12_000, "interrupted", interruption="network")
    assert answer["action"] == "resume"
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == []


def expire_at(url: str, attempt: str, now: datetime) -> None:
    async def run() -> None:
        database = Database(conninfo_to_url(url), pool_size=1)
        try:
            await blind_jobs.expire_attempt(database, uuid.UUID(attempt), now)
        finally:
            await database.dispose()

    asyncio.run(run())


def test_worker_uses_short_silence_timeout_after_resume(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session_id))
    clock.advance(40_000)
    assert beat(client, attempt, START, "interrupted", interruption="network")["action"] == "resume"
    due = clock.now + timedelta(milliseconds=MAX_SILENCE_MS + 1)
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s AND args->>'attempt_id' = %s AND scheduled_at = %s",
            [blind_jobs.EXPIRE_ATTEMPT, attempt, due],
        ).fetchone() == (1,)
    expire_at(migrated_url, attempt, due)
    expire_at(migrated_url, attempt, due)
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == [
        ("blind_abandoned", None, {"reason": "missed_heartbeat"})
    ]


def test_worker_preserves_a_completed_listen(
    client: TestClient, clock: Clock, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, END)
    clock.advance(300_000)
    expire_at(migrated_url, attempt, clock.now)
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == []
    assert (
        client.post(
            f"/api/v1/blind/attempts/{attempt}/gist", json={"text": SENTENCES_3}
        ).status_code
        == 201
    )


def test_worker_failure_rolls_back_and_retry_records_once(
    client: TestClient, clock: Clock, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = attempt_id(start_attempt(client, session_id))
    clock.advance(300_000)

    async def fail_publish(*args: object, **kwargs: object) -> None:
        raise RuntimeError("publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(blind_jobs, "publish", fail_publish)
        with pytest.raises(RuntimeError, match="publication failed"):
            expire_at(migrated_url, attempt, clock.now)
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT status FROM practice.attempts WHERE id = %s", [attempt]
        ).fetchone() == ("active",)
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == []
    expire_at(migrated_url, attempt, clock.now)
    expire_at(migrated_url, attempt, clock.now)
    assert len(events_of(migrated_url, learner_id(client), "blind_abandoned")) == 1


def test_recovery_committing_while_worker_waits_on_lock_is_preserved(
    client: TestClient, clock: Clock, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    attempt = uuid.UUID(attempt_id(start_attempt(client, session_id)))
    clock.advance(299_999)

    async def race() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=2)
        entered = asyncio.Event()
        original_get = blind_jobs.repository.get

        async def observed_get(db: AsyncSession, attempt_id: uuid.UUID, *, lock: bool = False):
            entered.set()
            return await original_get(db, attempt_id, lock=lock)

        try:
            async with database.transaction() as db:
                await original_get(db, attempt, lock=True)
                monkeypatch.setattr(blind_jobs.repository, "get", observed_get)
                worker = asyncio.create_task(
                    blind_jobs.expire_attempt(
                        database, attempt, clock.now + timedelta(milliseconds=1)
                    )
                )
                await asyncio.wait_for(entered.wait(), timeout=5)
                result = await blind_service.heartbeat(
                    db,
                    attempt,
                    Beat(START, PlayerState.INTERRUPTED, interruption=Interruption.NETWORK),
                    clock.now,
                )
                assert result.action.value == "resume"
            await asyncio.wait_for(worker, timeout=5)
        finally:
            await database.dispose()

    asyncio.run(race())
    assert events_of(migrated_url, learner_id(client), "blind_abandoned") == []


def test_dictation_records_the_first_play_not_the_screen_open(
    client: TestClient, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "dictation")
    for _ in range(2):  # the second opening resumes the live attempt
        opened = client.post(f"/api/v1/sessions/{session_id}/dictation/attempts")
        assert opened.status_code in (200, 201), opened.text
    attempt = opened.json()["id"]

    assert events_of(migrated_url, learner_id(client), "listen_started") == []
    for _ in range(2):  # a retry and later play are the same occurrence
        played = client.post(f"/api/v1/dictation/attempts/{attempt}/listen")
        assert played.status_code == 204, played.text

    assert events_of(migrated_url, learner_id(client), "listen_started") == [
        ("listen_started", None, {"mode": "dictation"})
    ]


def test_an_entry_change_starts_a_step_once_per_session(
    client: TestClient, migrated_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    session = load(client, {"id": session_id})
    session = change_entry(client, session, "dictation").json()
    change_entry(client, session, "blind")  # back to Blind: already started once

    assert kinds(events_of(migrated_url, learner_id(client))) == Counter(
        {("plan_started", None): 1, ("step_started", "blind"): 1, ("step_started", "dictation"): 1}
    )


def test_skips_complete_card_and_shadow_with_their_outcome(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    session_id = new_session(client, migrated_url, "blind")
    finish(api_role_url, client, session_id, Step.BLIND, Step.TRANSCRIPT)
    session = load(client, {"id": session_id})
    assert skip(client, session, "card", confirmed=False).status_code == 422  # not recorded
    session = skip(client, session, "card").json()
    skip(client, session, "shadow")

    learner = learner_id(client)
    assert events_of(migrated_url, learner, "step_completed") == [
        ("step_completed", "blind", {"outcome": "done"}),
        ("step_completed", "transcript", {"outcome": "done"}),
        ("step_completed", "card", {"outcome": "skipped"}),
        ("step_completed", "shadow", {"outcome": "skipped"}),
    ]
    assert [s for _, s, _ in events_of(migrated_url, learner, "step_started")] == [
        "blind",
        "transcript",
        "card",
        "shadow",
    ]


def test_features_still_to_come_record_each_occurrence_once(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    """Marks, cards, Shadow rounds and Dictation replays call these once they exist."""
    learner = uuid.UUID(learner_id(client))
    session, mark, card, round_id, attempt = (uuid.uuid4() for _ in range(5))

    async def record(db: AsyncSession) -> None:
        for _ in range(2):
            await analytics.record_mark_created(db, learner, session, mark, phrase="Could've")
            await analytics.record_card_created(db, learner, session, card)
            await analytics.record_shadow_round_completed(
                db, learner, session, round_id, round_number=1
            )
            await analytics.record_dictation_replays(db, learner, session, attempt, replay_count=7)

    in_transaction(api_role_url, learner, record)

    events = events_of(migrated_url, learner)
    assert kinds(events) == Counter(
        {
            ("mark_created", None): 1,
            ("card_created", None): 1,
            ("shadow_round_completed", None): 1,
            ("dictation_replays", None): 1,
        }
    )
    props = {kind: p for kind, _, p in events}
    assert props["shadow_round_completed"] == {"round": 1}
    assert props["dictation_replays"] == {"replay_count": 7}
    assert set(props["mark_created"]) == {"pattern"}  # a hash, never the phrase
    assert "could" not in json.dumps(props["mark_created"]).lower()


def test_an_event_that_cannot_be_recorded_does_not_fail_the_action(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    """A value analytics does not know is dropped; the caller's work still commits."""
    learner = uuid.UUID(learner_id(client))
    content, session = uuid.uuid4(), uuid.uuid4()

    async def record(db: AsyncSession) -> None:
        await analytics.record_content_added(db, learner, content, source_type="podcast")
        await analytics.record_plan_started(
            db, learner, session, content, path="blind", steps={"blind": "open", "karaoke": "open"}
        )
        await analytics.record_card_created(db, learner, session, uuid.uuid4())

    in_transaction(api_role_url, learner, record)

    assert kinds(events_of(migrated_url, learner)) == Counter(
        {("plan_started", None): 1, ("card_created", None): 1}
    )


def test_the_api_role_may_insert_its_own_events_only(
    make_client: ClientFactory, migrated_url: str, api_role_url: str
) -> None:
    mine = uuid.UUID(learner_id(make_client()))
    theirs = uuid.UUID(learner_id(make_client()))

    async def as_someone_else(db: AsyncSession) -> None:
        await analytics.record_card_created(db, theirs, uuid.uuid4(), uuid.uuid4())

    with pytest.raises(DBAPIError, match="row-level security"):
        in_transaction(api_role_url, mine, as_someone_else)

    with psycopg.connect(api_role_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT count(*) FROM ops.analytics_events")
    assert events_of(migrated_url, theirs) == []


# -- AC3: removed on account deletion -------------------------------------------------


def test_deleting_the_account_removes_its_events(migrated_url: str) -> None:
    gone, kept = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        for user in (gone, kept):
            conn.execute(
                "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
                [user, f"{user}@example.com"],
            )
    owner = conninfo_to_url(migrated_url)
    for user in (gone, kept):

        async def record(db: AsyncSession, user: uuid.UUID = user) -> None:
            await analytics.record_card_created(db, user, uuid.uuid4(), uuid.uuid4())

        in_transaction(owner, user, record)

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM identity.users WHERE id = %s", [gone])  # what the purge does

    assert events_of(migrated_url, gone) == []
    assert len(events_of(migrated_url, kept)) == 1


# -- AC2: the report ------------------------------------------------------------------

# Far from the other tests' events (stamped now), so this range holds only these.
DAY = datetime(2031, 3, 2, tzinfo=UTC)


def at(hours: float) -> datetime:
    return datetime.fromtimestamp(DAY.timestamp() + hours * 3600, UTC)


@pytest.fixture
def history(migrated_url: str) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """Two learners' events in March 2031, written as past events with their times."""
    a, b = uuid.uuid4(), uuid.uuid4()
    s1, s2, s3, s4, clip = (uuid.uuid4() for _ in range(5))
    new = uuid.uuid4
    # (learner, event, subject, step, content, session, properties, hours after DAY)
    rows: list[tuple[uuid.UUID, str, uuid.UUID, str | None, Any, Any, str, float]] = [
        (a, "content_added", clip, None, clip, None, '{"source_type": "upload"}', 0),
        (a, "plan_started", s1, None, clip, s1, '{"path": "blind"}', 0.005),
        (a, "listen_started", new(), None, clip, s1, '{"mode": "blind"}', 0.01),
        (a, "step_started", s1, "transcript", clip, s1, "{}", 1),
        (a, "mark_created", new(), None, None, s1, '{"pattern": "p1"}', 1),
        (a, "step_started", s1, "shadow", clip, s1, "{}", 2),
        (a, "card_created", new(), None, None, s1, "{}", 2),
        (a, "step_completed", s1, "shadow", clip, s1, '{"outcome": "done"}', 3),
        (a, "plan_started", s2, None, clip, s2, '{"path": "blind"}', 24),
        (a, "mark_created", new(), None, None, s2, '{"pattern": "p1"}', 25),
        (a, "plan_started", s3, None, clip, s3, '{"path": "blind"}', 48),
        (b, "plan_started", s4, None, None, s4, '{"path": "both"}', 1),
    ]
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        for user in (a, b):
            conn.execute(
                "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
                [user, f"{user}@example.com"],
            )
        for user, kind, subject, step, content, session, props, hours in rows:
            conn.execute(
                "INSERT INTO ops.analytics_events (id, user_id, event_type, subject_id, step, "
                "content_id, session_id, properties, occurred_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [new(), user, kind, subject, step, content, session, props, at(hours)],
            )
        yield a, b
        conn.execute("DELETE FROM identity.users WHERE id = ANY(%s)", [[a, b]])


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analytics_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_report_computes_the_five_metrics_for_a_date_range(
    history: tuple[uuid.UUID, uuid.UUID], migrated_url: str
) -> None:
    script = load_script()
    output = script.main(
        [
            "--from=2031-03-02",
            "--to=2031-03-02",  # one day: A's later plans are follow-ups, not cohort
            "--as-of=2031-04-01T00:00:00",
            "--role=listenup_readonly",
            f"--database-url={conninfo_to_url(migrated_url)}",
            "--json",
        ]
    )
    report = json.loads(output)

    assert report["plan_completion"] == {
        "started": 2,
        "reached_final_step": 1,
        "completed": 1,
        "reach_rate": 0.5,
        "completion_rate": 0.5,
    }
    assert report["first_listen"]["clips_added"] == 1
    assert report["first_listen"]["median_seconds"] == pytest.approx(36)
    assert report["first_listen"]["under_target_rate"] == 1.0
    assert report["return_rate"] == {
        "new_learners": 2,
        "returned": 1,
        "window_open": 0,
        "rate": 0.5,
    }
    assert report["mark_reuse"]["sessions_reached_transcript"] == 1
    assert report["mark_reuse"]["cards"] == 1
    assert report["mark_reuse"]["rate"] == 1.0
    assert report["repeat_failures"]["marks"] == 1  # the second mark is on 3 March
    assert report["repeat_failures"]["repeats"] == 0
    assert all("share" in row for row in report["repeat_failures"]["by_session"])


def test_the_report_follows_repeats_into_later_days(
    history: tuple[uuid.UUID, uuid.UUID], migrated_url: str
) -> None:
    text = load_script().main(
        [
            "--from=2031-03-02",
            "--to=2031-03-08",
            "--as-of=2031-04-01T00:00:00",
            "--role=listenup_readonly",
            f"--database-url={conninfo_to_url(migrated_url)}",
        ]
    )

    assert "Plan completion rate   25% reached the final step" in text
    assert "Repeat-failure trend   50% of 2 marks" in text
    assert "session 2: 100% of 1 marks" in text


def test_the_report_role_reads_events_but_no_account_data(
    history: tuple[uuid.UUID, uuid.UUID], migrated_url: str
) -> None:
    with psycopg.connect(migrated_url) as conn:
        conn.execute("SET ROLE listenup_readonly")
        seen = conn.execute(
            "SELECT count(DISTINCT user_id) FROM ops.analytics_events WHERE user_id = ANY(%s)",
            [list(history)],
        ).fetchone()
        assert seen == (2,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO ops.analytics_events DEFAULT VALUES")
        conn.rollback()
        conn.execute("SET ROLE listenup_readonly")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM identity.users")
