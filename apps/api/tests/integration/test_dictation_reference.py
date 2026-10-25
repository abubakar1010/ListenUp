"""The reference words the scoring job reads from the transcript cache (#54).

FR-DI-5, FR-TX-5: the words are for scoring only; no route returns them before submission.
"""

import uuid

import psycopg
import pytest

from listenup.modules.practice import service as practice
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from tests.integration.conftest import conninfo_to_url
from tests.integration.dictation_helpers import (
    PASSAGE,
    REFERENCE_WORDS,
    media_of,
    seed_transcript,
)
from tests.integration.seed import add_clip


async def start_dictation(database, learner, content):
    async with database.transaction(learner) as db:
        return await practice.start_plan(
            db, learner, content, PASSAGE["start_ms"], PASSAGE["end_ms"], practice.Entry.DICTATION
        )


@pytest.mark.anyio
async def test_reference_for_scoring_returns_passage_words_while_dictation_is_open(
    migrated_url, learner
):
    from listenup.modules.transcript import service

    _, content, _ = add_clip(migrated_url, learner)
    seed_transcript(migrated_url, media_of(migrated_url, str(content)))
    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start_dictation(database, learner, content)
        async with database.transaction(learner) as db:
            reference = await service.reference_for_scoring(db, database, learner, session.id)
        assert reference.words == REFERENCE_WORDS
        assert reference.start_ms[:2] == [1000, 2000]
        assert len(reference.end_ms) == len(REFERENCE_WORDS)
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_reference_for_scoring_says_not_ready_without_a_cached_passage(migrated_url, learner):
    from listenup.modules.transcript import service

    _, content, _ = add_clip(migrated_url, learner)
    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start_dictation(database, learner, content)
        async with database.transaction(learner) as db:
            with pytest.raises(ProblemError) as raised:
                await service.reference_for_scoring(db, database, learner, session.id)
        assert raised.value.code == "transcript_not_ready"
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_transcript_overlay_applies_to_own_dictation_scoring_reference(migrated_url, learner):
    from listenup.modules.transcript import service

    _, content, _ = add_clip(migrated_url, learner)
    media = media_of(migrated_url, str(content))
    seed_transcript(migrated_url, media)
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "INSERT INTO content.transcript_corrections "
            "(user_id, passage_transcript_id, word_index, corrected_text) "
            "SELECT %s, id, 0, 'Learner edit' FROM content.passage_transcripts "
            "WHERE media_object_id=%s",
            [learner, media],
        )
    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start_dictation(database, learner, content)
        async with database.transaction(learner) as db:
            reference = await service.reference_for_scoring(db, database, learner, session.id)
        assert reference.words == ["Learner edit", *REFERENCE_WORDS[1:]]
        assert reference.edited_word_indices == [0]
        async with database.transaction(learner) as db:
            await practice.complete_step(
                db, await practice.get_session(db, session.id), practice.Step.DICTATION
            )
        async with database.transaction(learner) as db:
            review = await service.read_passage(db, database, learner, session.id)
        assert review.words == ["Learner edit", *REFERENCE_WORDS[1:]]
        assert review.edited_word_indices == [0]
        assert review.start_ms == reference.start_ms
        assert review.end_ms == reference.end_ms
        assert review.sentence_starts == reference.sentence_starts
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_reference_for_scoring_refuses_another_learner_and_unreached_dictation(
    migrated_url, learner
):
    from listenup.modules.transcript import service

    _, content, _ = add_clip(migrated_url, learner)
    seed_transcript(migrated_url, media_of(migrated_url, str(content)))
    database = Database(conninfo_to_url(migrated_url))
    try:
        session = await start_dictation(database, learner, content)
        async with database.transaction(learner) as db:
            with pytest.raises(ProblemError) as stranger:
                await service.reference_for_scoring(db, database, uuid.uuid4(), session.id)
        assert stranger.value.code == "session_not_found"
        # A plan that starts with Blind has not reached Dictation yet.
        async with database.transaction(learner) as db:
            blind = await practice.start_plan(db, learner, content, 0, 60_000, practice.Entry.BOTH)
        async with database.transaction(learner) as db:
            with pytest.raises(ProblemError) as early:
                await service.reference_for_scoring(db, database, learner, blind.id)
        assert early.value.code == "step_locked"
    finally:
        await database.dispose()
