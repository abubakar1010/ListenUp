"""AT-6: numbered playback rounds are never recorded/uploaded completion."""

import uuid

import psycopg
import pytest

from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import FakeStorage, client_factory, learner_id
from tests.integration.test_review_api import cache
from tests.integration.test_shadow_segment import open_shadow, path


@pytest.fixture
def client(api_role_url, migrated_url):
    for make in client_factory(api_role_url, FakeStorage()):
        yield make(
            transcript_read_database_url=conninfo_to_url(migrated_url)
            + "?options=-c%20role%3Dlistenup_worker"
        )


def setup(client, migrated_url, api_role_url):
    sid = open_shadow(client, migrated_url, api_role_url)
    with psycopg.connect(migrated_url) as db:
        clip = db.execute("SELECT content_id FROM practice.sessions WHERE id=%s", [sid]).fetchone()[
            0
        ]
    cache(migrated_url, clip)
    assert client.put(path(sid), json={"start_ms": 10000, "end_ms": 70000}).status_code == 200
    return sid


def base(sid):
    return f"/api/v1/sessions/{sid}/shadow/rounds"


def start_round(client, sid, number, key=None):
    return client.post(
        f"{base(sid)}/{number}/start", headers={"Idempotency-Key": key or str(uuid.uuid4())}
    )


def end_round(client, sid, number):
    return client.post(
        f"{base(sid)}/{number}/playback-ended", headers={"Idempotency-Key": str(uuid.uuid4())}
    )


def test_three_rounds_disclosure_fourth_refusal_and_no_recording(
    client, migrated_url, api_role_url
):
    sid = setup(client, migrated_url, api_role_url)
    initial = client.get(base(sid)).json()
    assert initial["current"] is None and initial["rounds"] == [] and "text" not in initial
    key = str(uuid.uuid4())
    for number in (1, 2, 3):
        response = start_round(client, sid, number, key if number == 1 else None)
        assert response.status_code == 204, response.text
        response = client.get(base(sid))
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["current"]["round"] == number
        assert data["current"]["transcript_shown"] is (number == 1)
        assert data["current"]["recorded_at"] is None
        assert response.headers["cache-control"] == "private, no-store"
        if number == 1:
            assert data["text"] == "Hello world. Again."
            assert "Outside." not in response.text
        else:
            assert "text" not in data
            assert not any(word in response.text for word in ("Hello", "world", "Again", "Outside"))
            replay = start_round(client, sid, 1, key)
            assert replay.status_code == 204 and replay.content == b""
            assert start_round(client, sid, 1).status_code == 409
        assert (
            client.put(path(sid), json={"start_ms": 0, "end_ms": 60000}).json()["code"]
            == "segment_locked"
        )
        assert end_round(client, sid, number).status_code == 204
        assert end_round(client, sid, number).status_code == 204
        if number == 1:
            # Later rounds must not read/wait for transcript/profile work.
            with psycopg.connect(migrated_url) as db:
                db.execute(
                    "DELETE FROM content.passage_transcripts WHERE media_object_id IN "
                    "(SELECT c.media_object_id FROM content.contents c JOIN practice.sessions s "
                    "ON s.content_id=c.id WHERE s.id=%s)",
                    [sid],
                )
    assert start_round(client, sid, 4).status_code == 409
    assert start_round(client, sid, 4).json()["code"] == "round_limit"
    session = client.get(f"/api/v1/sessions/{sid}").json()
    assert session["open_step"] == "shadow" and session["completed_at"] is None
    with psycopg.connect(migrated_url, autocommit=True) as db:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO practice.shadow_rounds (id,session_id,user_id,round) "
                "VALUES (%s,%s,%s,4)",
                [uuid.uuid4(), sid, learner_id(client)],
            )
        assert (
            db.execute(
                "SELECT count(*) FROM practice.shadow_rounds WHERE session_id=%s "
                "AND recorded_at IS NOT NULL",
                [sid],
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT count(*) FROM ops.analytics_events WHERE session_id=%s "
                "AND event_type='shadow_round_completed'",
                [sid],
            ).fetchone()[0]
            == 0
        )


def test_round_numbers_are_sequential_and_end_requires_current_round(
    client, migrated_url, api_role_url
):
    sid = setup(client, migrated_url, api_role_url)
    assert start_round(client, sid, 2).status_code == 409
    assert start_round(client, sid, 0).status_code == 409
    assert end_round(client, sid, 1).status_code == 409
    assert start_round(client, sid, 1).status_code == 204
    assert start_round(client, sid, 1).status_code == 204
    assert start_round(client, sid, 2).status_code == 409
    assert end_round(client, sid, 2).status_code == 409


@pytest.mark.parametrize("number", [0, 2, 4])
def test_database_rejects_invalid_or_skipped_round(client, migrated_url, api_role_url, number):
    sid = setup(client, migrated_url, api_role_url)
    with psycopg.connect(migrated_url) as db, pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO practice.shadow_rounds (id,session_id,user_id,round) VALUES (%s,%s,%s,%s)",
            [uuid.uuid4(), sid, learner_id(client), number],
        )


def test_round_operations_require_shadow_step(client, migrated_url, api_role_url):
    from tests.integration.test_sessions_api import add_clip, start

    sid = start(client, add_clip(migrated_url, learner_id(client)))["id"]
    for response in (client.get(base(sid)), start_round(client, sid, 1), end_round(client, sid, 1)):
        assert response.status_code == 409
        assert response.json()["code"] == "step_locked"


def test_database_generated_visibility_and_immutable_number(client, migrated_url, api_role_url):
    sid = setup(client, migrated_url, api_role_url)
    assert start_round(client, sid, 1).status_code == 204
    with psycopg.connect(migrated_url, autocommit=True) as db:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("UPDATE practice.shadow_rounds SET round=2 WHERE session_id=%s", [sid])
        with pytest.raises(psycopg.errors.GeneratedAlways):
            db.execute(
                "UPDATE practice.shadow_rounds SET transcript_shown=false WHERE session_id=%s",
                [sid],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO practice.shadow_rounds (id,session_id,user_id,round) "
                "VALUES (%s,%s,%s,1)",
                [uuid.uuid4(), sid, learner_id(client)],
            )


@pytest.mark.parametrize("following", ["start", "edit", "skip"])
def test_concurrent_round_start_serializes(client, migrated_url, api_role_url, following):
    """Characterization: observe actual PostgreSQL waits in independent transactions."""
    import asyncio

    from sqlalchemy import text

    from listenup.modules.practice import service as practice
    from listenup.modules.shadow import schemas, service
    from listenup.platform.database import Database
    from listenup.platform.errors import ProblemError

    sid = uuid.UUID(setup(client, migrated_url, api_role_url))
    learner = uuid.UUID(learner_id(client))
    marker = f"round-race-{uuid.uuid4()}"

    async def run():
        database = Database(api_role_url)
        ready = asyncio.Event()

        async def second():
            async with database.transaction(learner) as db:
                await db.execute(
                    text("SELECT set_config('application_name', :name, true)"), {"name": marker}
                )
                ready.set()
                if following == "edit":
                    await service.segment(db, sid, schemas.SegmentChoice(start_ms=0, end_ms=60000))
                elif following == "skip":
                    session = await practice.require_step(db, sid, practice.Step.SHADOW)
                    await practice.skip_step(db, session, practice.Step.SHADOW, confirmed=True)
                else:
                    await service.change_round(db, sid, 1)

        try:
            async with database.transaction(learner) as db:
                await service.change_round(db, sid, 1)
                task = asyncio.create_task(second())
                await ready.wait()
                async with await psycopg.AsyncConnection.connect(
                    migrated_url, autocommit=True
                ) as observer:
                    async with asyncio.timeout(5):
                        while True:
                            row = await (
                                await observer.execute(
                                    "SELECT wait_event_type FROM pg_stat_activity "
                                    "WHERE application_name=%s",
                                    [marker],
                                )
                            ).fetchone()
                            if row and row[0] == "Lock":
                                break
                            assert not task.done(), "operation bypassed session serialization"
                            await asyncio.sleep(0.01)
            if following == "edit":
                with pytest.raises(ProblemError) as error:
                    await asyncio.wait_for(task, 5)
                assert error.value.code == "segment_locked"
            else:
                await asyncio.wait_for(task, 5)
        finally:
            if "task" in locals() and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await database.dispose()

    asyncio.run(run())
    with psycopg.connect(migrated_url) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM practice.shadow_rounds WHERE session_id=%s", [sid]
            ).fetchone()[0]
            == 1
        )


def test_round_ownership_is_enforced_by_composite_fk_and_rls(client, migrated_url, api_role_url):
    sid = setup(client, migrated_url, api_role_url)
    other = uuid.uuid4()
    with (
        psycopg.connect(migrated_url, autocommit=True) as db,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        db.execute(
            "INSERT INTO practice.shadow_rounds (id,session_id,user_id,round) VALUES (%s,%s,%s,1)",
            [uuid.uuid4(), sid, other],
        )
    with psycopg.connect(api_role_url, autocommit=True) as db:
        db.execute("SELECT set_config('app.user_id',%s,false)", [learner_id(client)])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(
                "INSERT INTO practice.shadow_rounds (id,session_id,user_id,round) "
                "VALUES (%s,%s,%s,1)",
                [uuid.uuid4(), sid, other],
            )


def test_round_replay_after_skip_refuses(client, migrated_url, api_role_url):
    """After a committed skip, even replay keys cannot bypass the step gate."""

    sid = setup(client, migrated_url, api_role_url)
    key = str(uuid.uuid4())
    assert start_round(client, sid, 1, key).status_code == 204
    version = client.get(f"/api/v1/sessions/{sid}").json()["version"]
    skipped = client.post(
        f"/api/v1/sessions/{sid}/steps/shadow/skip", json={"confirmed": True, "version": version}
    )
    assert skipped.status_code == 200, skipped.text
    for response in (
        client.get(base(sid)),
        start_round(client, sid, 1, key),
        end_round(client, sid, 1),
    ):
        assert response.status_code == 409
        assert response.json()["code"] in ("step_locked", "session_closed")
