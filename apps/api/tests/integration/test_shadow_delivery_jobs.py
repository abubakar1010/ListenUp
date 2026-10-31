"""#82 synthetic delivery pipeline; these tests establish no speech-quality evidence."""

import asyncio
import uuid

import psycopg
import pytest

from tests.integration.intake_helpers import learner_id
from tests.integration.test_shadow_recording import (
    client as client,
)
from tests.integration.test_shadow_recording import (
    make as make,
)
from tests.integration.test_shadow_recording import (
    record_round,
)
from tests.integration.test_shadow_recording import (
    storage as storage,
)
from tests.integration.test_shadow_rounds import setup


@pytest.fixture
def recorded(client, storage, migrated_url, api_role_url):
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    return uuid.UUID(body["round_id"]), learner_id(client), sid


def test_recording_queues_one_lane_one_job_and_private_pending_grade(migrated_url, recorded):
    round_id, learner, _ = recorded
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status,measures FROM grading.round_grades WHERE round_id=%s AND user_id=%s",
            [round_id, learner],
        ).fetchone() == ("pending", None)
        rows = db.execute(
            "SELECT queue_name,args FROM procrastinate.procrastinate_jobs "
            "WHERE task_name='grading.grade_round' AND args->>'round_id'=%s",
            [str(round_id)],
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "speech-interactive"
        assert set(rows[0][1]) <= {
            "round_id",
            "user_id",
            "generation",
            "_request_id",
            "_traceparent",
        }
        assert rows[0][1]["user_id"] == str(learner)


def test_round_grade_rls_and_owner_constraint(migrated_url, api_role_url, recorded):
    round_id, learner, _ = recorded
    with psycopg.connect(api_role_url) as db:
        assert db.execute("SELECT round_id FROM grading.round_grades").fetchall() == []
        db.execute("SELECT set_config('app.user_id',%s,true)", [str(uuid.uuid4())])
        assert db.execute("SELECT round_id FROM grading.round_grades").fetchall() == []
        db.execute("SELECT set_config('app.user_id',%s,true)", [str(learner)])
        assert db.execute("SELECT round_id FROM grading.round_grades").fetchall() == [(round_id,)]
    with psycopg.connect(migrated_url) as db:
        with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
            db.execute(
                "UPDATE grading.round_grades SET user_id=%s WHERE round_id=%s",
                [uuid.uuid4(), round_id],
            )
        db.execute("DELETE FROM practice.shadow_rounds WHERE id=%s", [round_id])
        assert (
            db.execute(
                "SELECT 1 FROM grading.round_grades WHERE round_id=%s", [round_id]
            ).fetchone()
            is None
        )


def test_assessment_source_authorizes_round_and_uses_original_words(migrated_url, recorded):
    from listenup.modules.shadow import service as shadow
    from listenup.modules.transcript import service as transcript
    from listenup.platform.database import Database
    from listenup.platform.errors import ProblemError
    from tests.integration.conftest import conninfo_to_url

    round_id, learner, sid = recorded

    async def check():
        database = Database(conninfo_to_url(migrated_url))
        try:
            async with database.transaction(uuid.UUID(learner)) as db:
                source = await shadow.assessment_source(db, uuid.UUID(learner), round_id)
                assert source.session_id == uuid.UUID(sid)
                assert source.span == (10_000, 70_000)
                assert source.recording_key.startswith(f"users/{learner}/shadow/")
                words = await transcript.reference_for_shadow(
                    db, database, uuid.UUID(learner), source.session_id
                )
                assert words.words == ["Outside.", "Hello", "world.", "Again."]
            async with database.transaction() as db:
                with pytest.raises(ProblemError) as refused:
                    await shadow.assessment_source(db, uuid.uuid4(), round_id)
                assert refused.value.status == 404
        finally:
            await database.dispose()

    asyncio.run(check())


@pytest.fixture
def run_round(migrated_url, recorded, storage, monkeypatch):
    from listenup.ai.config import AIConfig, ProviderEntry
    from listenup.ai.gateway import AIGateway
    from listenup.ai.ports import Role
    from listenup.ai.providers.fake_assessment import FakeAssessment
    from listenup.modules.grading import jobs
    from listenup.modules.transcript import service as transcript
    from listenup.platform.database import Database
    from listenup.platform.jobs import JobDeps
    from tests.integration.conftest import conninfo_to_url

    round_id, learner, sid = recorded
    gateway = AIGateway(
        AIConfig(
            version=1,
            roles={
                Role.SPEECH_ASSESSMENT: (
                    ProviderEntry(
                        provider="fake-assessment",
                        model="synthetic-v1",
                        accepted=True,
                        local=True,
                        trains_on_inputs=False,
                    ),
                )
            },
        )
    )
    monkeypatch.setattr(jobs, "get_gateway", lambda: gateway)
    monkeypatch.setattr(jobs, "get_storage", lambda: storage)
    calls, published = [], []
    assess = FakeAssessment.assess
    publish = jobs.publish

    async def capture(self, recording, reference_text, reference_audio):
        calls.append(reference_text)
        assert recording.read_bytes() == b"synthetic recording"
        assert reference_audio.exists()
        return await assess(self, recording, reference_text, reference_audio)

    async def event(*args):
        published.append(args[1:])
        await publish(*args)

    monkeypatch.setattr(FakeAssessment, "assess", capture)
    monkeypatch.setattr(jobs, "publish", event)
    # The profile boundary is independently covered by #76; synthetic evidence here
    # uses real transcript identities and explicit original timings.
    with psycopg.connect(migrated_url) as db:
        row = db.execute(
            "SELECT recording_key FROM practice.shadow_rounds WHERE id=%s", [round_id]
        ).fetchone()
        storage.data[row[0]] = b"synthetic recording"
        media, playback = db.execute(
            "SELECT c.media_object_id,m.playback_key FROM practice.sessions s "
            "JOIN content.contents c ON c.id=s.content_id "
            "JOIN content.media_objects m ON m.id=c.media_object_id "
            "WHERE s.id=%s",
            [sid],
        ).fetchone()
        transcript_id = db.execute(
            "SELECT id FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchone()[0]
        if playback is None:
            playback = f"media/{media}/playback.mp4"
            db.execute(
                "UPDATE content.media_objects SET playback_key=%s WHERE id=%s", [playback, media]
            )
        storage.data[playback] = b"synthetic original"
        generation = db.execute(
            "SELECT generation FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone()[0]

    async def profile(*args):
        return transcript.ProfileReadiness(
            "ready",
            "profiled",
            (
                transcript.ReferenceProfile(
                    transcript_id,
                    (0, 120000),
                    [0, 1, 2, 3],
                    [0, 11000, 12000, 30000],
                    [500, 11500, 13000, 31000],
                    [900] * 4,
                    [],
                    [],
                    10,
                    {"provider": "fixture", "model": "synthetic-profile", "version": "1"},
                ),
            ),
        )

    monkeypatch.setattr(transcript, "reference_profile", profile)

    async def run(generation_override=None):
        database = Database(conninfo_to_url(migrated_url))
        try:
            await jobs.grade_round(
                JobDeps(database, None, 1),
                str(round_id),
                learner,
                str(generation_override or generation),
            )
        finally:
            await database.dispose()

    return lambda **kw: asyncio.run(run(**kw)), calls, published, generation


def test_round_job_persists_measures_provenance_and_one_event(migrated_url, recorded, run_round):
    from listenup.platform.events import EventType

    run, calls, published, _ = run_round
    run()
    run()
    round_id, learner, _ = recorded
    with psycopg.connect(migrated_url) as db:
        status, measures, count, info = db.execute(
            "SELECT status,measures,filler_count,speech_info FROM grading.round_grades "
            "WHERE round_id=%s",
            [round_id],
        ).fetchone()
    assert status == "scored"
    assert set(measures) == {"timing", "fluency", "fillers", "completeness"}
    assert measures["timing"]["reason"] == "playback_offset_unknown"
    assert measures["completeness"]["score"] == 100
    assert count == 1
    assert info["provider"] == "fake-assessment" and info["model"] == "synthetic-v1"
    assert info["version"] == "1" and info["parameters_version"] == "1"
    assert info["synthetic"] is True
    assert info["echo"]["status"] == "unchecked"
    assert calls == ["Hello world. Again."]
    assert published == [(uuid.UUID(learner), EventType.GRADE_READY, round_id)]


def test_synthetic_grade_is_unavailable_and_retry_is_owned(client, make, recorded, run_round):
    round_id, _, _ = recorded
    run_round[0]()
    path = f"/api/v1/shadow/rounds/{round_id}/grade"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "private, no-store"
    assert client.post(path + "/retry").status_code == 202
    other = make()
    for method, url in (("GET", path), ("POST", path + "/retry")):
        refused = other.request(method, url)
        assert refused.status_code == 404 and refused.json()["code"] == "round_not_found"


def invoke(url, action):
    from listenup.platform.database import Database
    from tests.integration.conftest import conninfo_to_url

    async def run():
        database = Database(conninfo_to_url(url))
        try:
            return await action(database)
        finally:
            await database.dispose()

    return asyncio.run(run())


def test_provider_failure_keeps_recording_and_retry_can_score(
    migrated_url, recorded, run_round, monkeypatch
):
    from listenup.ai.providers.fake_assessment import FakeAssessment

    run, calls, published, _ = run_round
    assess = FakeAssessment.assess

    async def fail(*args):
        raise OSError("synthetic outage")

    monkeypatch.setattr(FakeAssessment, "assess", fail)
    from listenup.ai.errors import AIUnavailable

    with pytest.raises(AIUnavailable):
        run()
    round_id, _, _ = recorded
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status,measures FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone() == ("unavailable", None)
        assert (
            db.execute(
                "SELECT recording_key,recorded_at FROM practice.shadow_rounds WHERE id=%s",
                [round_id],
            ).fetchone()[0]
            is not None
        )
    assert published == []
    monkeypatch.setattr(FakeAssessment, "assess", assess)
    run()
    assert len(calls) == len(published) == 1


def test_event_failure_rolls_back_scores(migrated_url, recorded, run_round, monkeypatch):
    from listenup.modules.grading import jobs

    async def fail(*args):
        raise RuntimeError("event transaction failed")

    monkeypatch.setattr(jobs, "publish", fail)
    with pytest.raises(RuntimeError, match="event transaction failed"):
        run_round[0]()
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT measures,status FROM grading.round_grades WHERE round_id=%s", [recorded[0]]
        ).fetchone() == (None, "unavailable")


def test_pending_profile_reschedules_without_assessment(
    migrated_url, recorded, run_round, monkeypatch
):
    from listenup.modules.transcript import service as transcript
    from listenup.platform.jobs import Reschedule

    async def pending(*args):
        return transcript.ProfileReadiness("pending", "transcribed")

    monkeypatch.setattr(transcript, "reference_profile", pending)
    with pytest.raises(Reschedule):
        run_round[0]()
    assert run_round[1] == run_round[2] == []


def test_stale_generation_cannot_assess_or_change_new_cycle(migrated_url, recorded, run_round):
    from listenup.modules.grading import jobs
    from listenup.platform.jobs import JobDeps

    run, calls, published, generation = run_round
    round_id, learner, _ = recorded
    newer = uuid.uuid4()
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE grading.round_grades SET generation=%s WHERE round_id=%s", [newer, round_id]
        )
    run()

    async def callbacks(database):
        deps = JobDeps(database, None, 3)
        await jobs._round_give_up(deps, str(round_id), learner, str(generation))
        await jobs.round_deadline(deps, str(round_id), learner, str(generation))

    invoke(migrated_url, callbacks)
    assert calls == published == []
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status,generation FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone() == ("pending", newer)


def test_retry_coalesces_live_work_and_resets_only_admitted_cycle(
    client, migrated_url, recorded, run_round
):
    round_id, _, _ = recorded
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE grading.round_grades SET status='unavailable' WHERE round_id=%s", [round_id]
        )
    path = f"/api/v1/shadow/rounds/{round_id}/grade/retry"
    assert client.post(path).status_code == 202
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone() == ("unavailable",)
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs WHERE task_name='grading.grade_round' "
            "AND args->>'round_id'=%s",
            [str(round_id)],
        )
    assert client.post(path).status_code == 202
    assert client.post(path).status_code == 202
    with psycopg.connect(migrated_url) as db:
        state, newer = db.execute(
            "SELECT status,generation FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone()
        assert state == "pending" and newer != run_round[3]
        assert db.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name='grading.grade_round' "
            "AND args->>'round_id'=%s",
            [str(round_id)],
        ).fetchone() == (1,)


def test_finished_round_deadline_is_a_noop(migrated_url, recorded, run_round):
    from listenup.modules.grading import jobs
    from listenup.platform.jobs import JobDeps

    run_round[0]()
    round_id, learner, _ = recorded

    async def deadline(database):
        await jobs.round_deadline(
            JobDeps(database, None, 1), str(round_id), learner, str(run_round[3])
        )

    invoke(migrated_url, deadline)


@pytest.mark.parametrize("state", ["failed", "pending"])
def test_profile_state_never_calls_assessment(recorded, run_round, monkeypatch, state):
    from listenup.modules.transcript import service as transcript
    from listenup.platform.jobs import PermanentError, Reschedule

    async def profile(*args):
        return transcript.ProfileReadiness(state, "transcribed")

    monkeypatch.setattr(transcript, "reference_profile", profile)
    with pytest.raises(PermanentError if state == "failed" else Reschedule):
        run_round[0]()
    assert run_round[1] == run_round[2] == []


@pytest.mark.parametrize("target", ["recording", "original"])
def test_missing_audio_keeps_data_and_never_assesses(recorded, run_round, storage, target):
    from listenup.platform.jobs import PermanentError

    key = next(k for k in storage.data if ("/shadow/" in k) == (target == "recording"))
    del storage.data[key]
    with pytest.raises(PermanentError, match="object is missing"):
        run_round[0]()
    assert run_round[1] == run_round[2] == []


def test_withdrawn_voice_consent_prevents_assessment(client, recorded, run_round):
    assert (
        client.post("/api/v1/me/consents/withdraw", json={"kind": "voice_recording"}).status_code
        == 200
    )
    from listenup.platform.jobs import PermanentError

    with pytest.raises(PermanentError, match="Voice consent"):
        run_round[0]()
    assert run_round[1] == run_round[2] == []


def test_disabled_account_does_not_assess(migrated_url, recorded, run_round):
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE identity.users SET status='pending_deletion',deletion_scheduled_at=now() "
            "WHERE id=%s",
            [recorded[1]],
        )
    run_round[0]()
    assert run_round[1] == run_round[2] == []


def test_session_deleted_during_assessment_is_not_recreated(
    migrated_url, recorded, run_round, monkeypatch
):
    from listenup.ai.providers.fake_assessment import FakeAssessment

    assess = FakeAssessment.assess

    async def delete(self, *args):
        result = await assess(self, *args)
        with psycopg.connect(migrated_url) as db:
            db.execute("DELETE FROM practice.sessions WHERE id=%s", [recorded[2]])
        return result

    monkeypatch.setattr(FakeAssessment, "assess", delete)
    run_round[0]()
    assert run_round[2] == []
    with psycopg.connect(migrated_url) as db:
        assert (
            db.execute(
                "SELECT 1 FROM grading.round_grades WHERE round_id=%s", [recorded[0]]
            ).fetchone()
            is None
        )


def test_due_deadline_marks_unavailable_without_changing_recording(
    migrated_url, recorded, run_round
):
    from listenup.modules.grading import jobs
    from listenup.platform.jobs import JobDeps, Reschedule

    round_id, learner, _ = recorded

    async def deadline(database):
        await jobs.round_deadline(
            JobDeps(database, None, 1), str(round_id), learner, str(run_round[3])
        )

    with pytest.raises(Reschedule):
        invoke(migrated_url, deadline)
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE grading.round_grades SET feedback_deadline=now()-interval '1 second' "
            "WHERE round_id=%s",
            [round_id],
        )
    invoke(migrated_url, deadline)
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM grading.round_grades WHERE round_id=%s", [round_id]
        ).fetchone() == ("unavailable",)
        assert db.execute(
            "SELECT recorded_at IS NOT NULL FROM practice.shadow_rounds WHERE id=%s", [round_id]
        ).fetchone() == (True,)
    run_round[0]()  # a useful late result remains admissible
    assert len(run_round[2]) == 1


def test_e2_refuses_other_provider_before_any_audio(migrated_url, recorded, run_round, monkeypatch):
    from listenup.ai.config import AIConfig, ProviderEntry
    from listenup.ai.gateway import AIGateway
    from listenup.ai.ports import Role
    from listenup.modules.grading import jobs
    from listenup.platform.jobs import PermanentError

    gateway = AIGateway(
        AIConfig(
            version=1,
            roles={
                Role.SPEECH_ASSESSMENT: (
                    ProviderEntry(
                        provider="fake", accepted=True, local=True, trains_on_inputs=False
                    ),
                )
            },
        )
    )
    monkeypatch.setattr(jobs, "get_gateway", lambda: gateway)
    with pytest.raises(PermanentError, match="E2 requires"):
        run_round[0]()
    assert run_round[1] == run_round[2] == []


def test_queue_and_grade_roll_back_together(migrated_url, recorded):
    from listenup.modules.grading import service

    round_id, learner, _ = recorded
    with psycopg.connect(migrated_url) as db:
        db.execute("DELETE FROM grading.round_grades WHERE round_id=%s", [round_id])
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs WHERE args->>'round_id'=%s",
            [str(round_id)],
        )

    async def enqueue(database):
        async with database.transaction(uuid.UUID(learner)) as db:
            await service.queue_round(db, uuid.UUID(learner), round_id)
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        invoke(migrated_url, enqueue)
    with psycopg.connect(migrated_url) as db:
        assert (
            db.execute(
                "SELECT 1 FROM grading.round_grades WHERE round_id=%s", [round_id]
            ).fetchone()
            is None
        )
        assert (
            db.execute(
                "SELECT 1 FROM procrastinate.procrastinate_jobs WHERE args->>'round_id'=%s",
                [str(round_id)],
            ).fetchone()
            is None
        )
