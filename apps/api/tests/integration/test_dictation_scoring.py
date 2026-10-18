"""Scoring a submitted Dictation in a job (#54; FR-DI-5, FR-TX-5, AT-3, ADR 0041).

The job reads the cached passage words with `transcript.reference_for_scoring`, scores
with the pure `score_dictation` and stores the diff in one idempotent update that also
publishes `dictation.scored`. A submission that finds no transcript waits; the
transcript job's `transcript.ready` hook queues the scoring again.
"""

import json

import psycopg
import pytest

from listenup.modules.dictation import jobs
from listenup.modules.dictation import service as dictation
from listenup.modules.practice import service as practice
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps
from tests.integration.conftest import conninfo_to_url
from tests.integration.dictation_helpers import (
    PASSAGE,
    media_of,
    seed_transcript,
)
from tests.integration.seed import add_clip

# AT-3: the reference is "Cities plant street trees to cool the air in summer." and the
# learner typed "street" as "streat" (a spelling slip), left out "to" and added "quickly".
TYPED = "Cities plant streat trees cool the air in quickly summer"
EXPECTED_WORDS = [
    {"index": 0, "word": "Cities", "status": "correct", "typed": "Cities"},
    {"index": 1, "word": "plant", "status": "correct", "typed": "plant"},
    {"index": 2, "word": "street", "status": "spelling_slip", "typed": "streat"},
    {"index": 3, "word": "trees", "status": "correct", "typed": "trees"},
    {"index": 4, "word": "to", "status": "missing", "typed": ""},
    {"index": 5, "word": "cool", "status": "correct", "typed": "cool"},
    {"index": 6, "word": "the", "status": "correct", "typed": "the"},
    {"index": 7, "word": "air", "status": "correct", "typed": "air"},
    {"index": 8, "word": "in", "status": "correct", "typed": "in"},
    {"index": 9, "word": "summer.", "status": "correct", "typed": "summer"},
]
EXPECTED_EXTRAS = [{"typed": "quickly", "before_index": 9}]


@pytest.fixture
def database(migrated_url):
    return Database(conninfo_to_url(migrated_url))


@pytest.fixture
def clip(migrated_url, learner):
    _, content, _ = add_clip(migrated_url, learner)
    return content


async def submitted(database, learner, content, text=TYPED):
    """A Dictation-only plan with its text submitted; returns (attempt id, session id)."""
    async with database.transaction(learner) as db:
        session = await practice.start_plan(
            db, learner, content, PASSAGE["start_ms"], PASSAGE["end_ms"], practice.Entry.DICTATION
        )
    async with database.transaction(learner) as db:
        work = await dictation.open_attempt(db, learner, session.id)
    async with database.transaction(learner) as db:
        await dictation.submit(db, work.attempt.id, text, session.version, 2)
    return work.attempt.id, session.id


async def score(database, learner, attempt_id, attempt=1):
    await jobs.score_attempt(JobDeps(database, None, attempt), str(attempt_id), str(learner))


def stored(migrated_url, attempt_id):
    with psycopg.connect(migrated_url) as conn:
        return conn.execute(
            "SELECT scoring_status, diff, accuracy, scored_at FROM practice.dictation_attempts "
            "WHERE attempt_id = %s",
            [attempt_id],
        ).fetchone()


def queued(migrated_url, attempt_id):
    with psycopg.connect(migrated_url) as conn:
        return conn.execute(
            "SELECT queue_name FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'dictation.score_attempt' AND args->>'attempt_id' = %s",
            [str(attempt_id)],
        ).fetchall()


async def scored_events(migrated_url, run):
    """The events published while `run()` ran."""
    with psycopg.connect(migrated_url, autocommit=True) as listener:
        listener.execute("LISTEN user_events")
        await run()
        return [json.loads(n.payload) for n in listener.notifies(timeout=0.5)]


@pytest.mark.anyio
async def test_at3_known_passage_and_text_give_the_expected_diff_and_accuracy(
    migrated_url, learner, clip, database
):
    seed_transcript(migrated_url, media_of(migrated_url, str(clip)))
    try:
        attempt, _ = await submitted(database, learner, clip)

        events = await scored_events(migrated_url, lambda: score(database, learner, attempt))

        status, diff, accuracy, scored_at = stored(migrated_url, attempt)
        assert status == "scored"
        assert diff["words"] == EXPECTED_WORDS
        assert diff["extras"] == EXPECTED_EXTRAS
        assert diff["slips_count_as_correct"] is True
        assert float(accuracy) == 90.0  # 8 correct + 1 spelling slip of 10 reference words
        assert scored_at is not None
        assert events == [{"u": str(learner), "t": "dictation.scored", "r": str(attempt)}]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_scoring_twice_changes_nothing_and_announces_once(
    migrated_url, learner, clip, database
):
    seed_transcript(migrated_url, media_of(migrated_url, str(clip)))
    try:
        attempt, _ = await submitted(database, learner, clip)

        async def twice():
            await score(database, learner, attempt)
            await score(database, learner, attempt, attempt=2)

        events = await scored_events(migrated_url, twice)

        assert len(events) == 1
        assert stored(migrated_url, attempt)[1]["words"] == EXPECTED_WORDS
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_a_submission_without_a_transcript_stays_waiting(
    migrated_url, learner, clip, database
):
    try:
        attempt, _ = await submitted(database, learner, clip)

        events = await scored_events(migrated_url, lambda: score(database, learner, attempt))

        assert stored(migrated_url, attempt)[:3] == ("waiting_transcript", None, None)
        assert events == []
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_a_failed_transcription_leaves_the_submission_waiting(
    migrated_url, learner, clip, database
):
    from listenup.modules.transcript import repository as cache

    media = media_of(migrated_url, str(clip))
    try:
        attempt, _ = await submitted(database, learner, clip)
        async with database.transaction() as db:
            await cache.mark_failed(db, media, [(0, 125_000)])

        await score(database, learner, attempt)

        assert stored(migrated_url, attempt)[0] == "waiting_transcript"
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_submit_queues_a_scoring_job_on_the_speech_lane_in_its_transaction(
    migrated_url, learner, clip, database
):
    try:
        attempt, _ = await submitted(database, learner, clip)

        assert queued(migrated_url, attempt) == [("speech-interactive",)]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_the_transcript_ready_hook_queues_scoring_for_waiting_submissions_only(
    migrated_url, learner, clip, database
):
    try:
        waiting, session = await submitted(database, learner, clip)
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM procrastinate.procrastinate_jobs")

        async with database.transaction(learner) as db:
            await dictation.on_transcript_ready(db, learner, session)
        assert queued(migrated_url, waiting) == [("speech-interactive",)]

        # Once scored, a later ready signal queues nothing.
        seed_transcript(migrated_url, media_of(migrated_url, str(clip)))
        await score(database, learner, waiting)
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
        async with database.transaction(learner) as db:
            await dictation.on_transcript_ready(db, learner, session)
        assert queued(migrated_url, waiting) == []
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_transcription_finishing_queues_scoring_of_a_waiting_submission(
    migrated_url, learner, clip, database, monkeypatch
):
    from listenup.modules.transcript import jobs as transcript_jobs
    from tests.unit.test_transcript_packing import result

    class Storage:
        async def download(self, key, target):
            target.write_bytes(b"audio")
            return object()

    class Gateway:
        async def transcribe(self, audio, language="en"):
            return result()

    async def extract(source, target, span):
        target.write_bytes(b"window")

    monkeypatch.setattr(transcript_jobs, "get_storage", lambda: Storage())
    monkeypatch.setattr(transcript_jobs, "get_gateway", lambda: Gateway())
    monkeypatch.setattr(transcript_jobs, "extract", extract)
    try:
        attempt, session = await submitted(database, learner, clip)
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM procrastinate.procrastinate_jobs")

        await transcript_jobs.transcribe_passage(
            JobDeps(database, None, 1), str(session), str(learner)
        )

        assert queued(migrated_url, attempt) == [("speech-interactive",)]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_a_concurrent_second_scorer_cannot_overwrite_the_first_score(
    migrated_url, learner, clip, database
):
    """Both scorers read `waiting`; only the first update may win (idempotent upsert)."""
    from listenup.modules.dictation import repository

    try:
        attempt, _ = await submitted(database, learner, clip)
        async with database.transaction(learner) as db:
            first = await repository.store_score(db, attempt, {"words": ["first"]}, 100)
        async with database.transaction(learner) as db:
            second = await repository.store_score(db, attempt, {"words": ["second"]}, 0)

        assert (first, second) == (True, False)
        status, diff, accuracy, _ = stored(migrated_url, attempt)
        assert (status, diff, float(accuracy)) == ("scored", {"words": ["first"]}, 100.0)
    finally:
        await database.dispose()
