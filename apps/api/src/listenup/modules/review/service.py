"""The Transcript experience composes public module services, never cache queries.

Marks (#58, FR-TR-2, ADR 0047) are this module's own rows in `practice.marks`. Every
mark route passes the Transcript gate (`practice.require_reached`) first. A new mark
is named by the browser and saved with one INSERT; its audio time and phrase come
from the passage words, never from the browser. Later stories add to these
functions: tags (#61), the mark list and count (#60), Dictation pre-fill (#59).

Marks added from the Dictation diff (#55, FR-DI-6) come through `add_dictation_marks`:
the dictation module places them from its stored diff and checks its own attempt, so
they need neither the Transcript gate nor the passage read.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.review import repository, schemas
from listenup.modules.review.domain import (
    MarkOutOfRange,
    MarkRuleError,
    MarkTooLong,
    MarkWithoutWords,
    check_length,
    clean_note,
    place_mark,
)
from listenup.modules.transcript import service as transcript
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows

Mark = schemas.Mark
"""A stored mark as the API shows it; other modules name the type through this service."""


async def read_transcript(
    db: AsyncSession, worker_database: Database, learner: uuid.UUID, session_id: uuid.UUID
) -> schemas.TranscriptReview:
    # FR-TX-5: this boundary authorizes ownership and step before privileged reads.
    # read_passage applies the learner's overlay using cache-row/local-word identity.
    # Review never queries corrections or changes the shared reference (#57).
    passage = await transcript.read_passage(db, worker_database, learner, session_id)
    session = await practice.get_session(db, session_id)
    item = await content.get_content(db, learner, session.content_id)
    edited = set(passage.edited_word_indices)
    words = [
        schemas.TranscriptWord(
            index=i,
            text=word,
            start_ms=start,
            end_ms=end,
            edited=i in edited,
        )
        for i, (word, start, end) in enumerate(
            zip(passage.words, passage.start_ms, passage.end_ms, strict=True)
        )
    ]
    boundaries = [*passage.sentence_starts, len(words)]
    lines = []
    for i, (left, right) in enumerate(pairwise(boundaries)):
        sentence = words[left:right]
        lines.append(
            schemas.TranscriptLine(
                index=i,
                start_ms=sentence[0].start_ms,
                end_ms=max(word.end_ms for word in sentence),
                words=sentence,
            )
        )
    return schemas.TranscriptReview(
        session_id=session_id,
        passage=schemas.TranscriptPassage(
            start_ms=session.passage.start_ms, end_ms=session.passage.end_ms
        ),
        media_url=f"/api/v1/media/{item.media_object_id}",
        lines=lines,
    )


def _mark(row: repository.MarkRow) -> schemas.Mark:
    return schemas.Mark.model_validate(row, from_attributes=True)


def _refused(error: MarkRuleError) -> ProblemError:
    if isinstance(error, MarkOutOfRange):
        return ProblemError(422, "mark_out_of_range", "Those words are not in this passage.")
    if isinstance(error, MarkWithoutWords):
        return ProblemError(422, "mark_no_words", "Removed words cannot be marked.")
    if isinstance(error, MarkTooLong):
        return ProblemError(422, "mark_too_long", "Mark a word or a short phrase.")
    return ProblemError(422, "note_too_long", "A note can be at most 500 characters.")


def _note(note: str | None) -> str | None:
    try:
        return clean_note(note)
    except MarkRuleError as error:
        raise _refused(error) from error


def _mark_not_found() -> ProblemError:
    return ProblemError(404, "mark_not_found", "There is no such mark.")


async def list_marks(db: AsyncSession, session_id: uuid.UUID) -> list[schemas.Mark]:
    """The session's marks in audio order, for showing them again after a reload."""
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    return await session_marks(db, session_id)


async def finish_transcript(db: AsyncSession, session_id: uuid.UUID) -> None:
    """FR-PL-4: finish Transcript and open Card in the request's transaction."""
    session = await practice.require_step(db, session_id, practice.Step.TRANSCRIPT)
    await practice.complete_step(db, session, practice.Step.TRANSCRIPT)


async def create_mark(
    db: AsyncSession,
    worker_database: Database,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    new: schemas.NewMark,
) -> tuple[schemas.Mark, bool]:
    """The mark and True when it is new; a resend of the same mark gives it back and False.

    Refusals: 409 `mark_exists` (these words are already marked; names that mark) and
    `mark_id_taken` (the id belongs to a different mark), 422 `mark_out_of_range`,
    `mark_too_long` and `note_too_long`.
    """
    note = _note(new.note)
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    passage = await transcript.read_passage(db, worker_database, learner, session_id)
    try:
        place = place_mark(new.word_from, new.word_to, passage.words, passage.start_ms)
    except MarkRuleError as error:
        raise _refused(error) from error
    row = await repository.insert(
        db,
        repository.NewMark(
            id=new.id,
            session_id=session_id,
            user_id=learner,
            word_from=new.word_from,
            word_to=new.word_to,
            at_ms=place.at_ms,
            note=note,
            source="manual",
        ),
    )
    if row is not None:
        await analytics.record_mark_created(db, learner, session_id, row.id, phrase=place.phrase)
        return _mark(row), True
    same = await repository.get(db, new.id)
    if same and (same.session_id, same.word_from, same.word_to) == (
        session_id,
        new.word_from,
        new.word_to,
    ):
        return _mark(same), False
    if same is None and (
        other := await repository.find_range(db, session_id, new.word_from, new.word_to)
    ):
        raise ProblemError(
            409, "mark_exists", "These words are already marked.", mark_id=str(other.id)
        )
    raise ProblemError(409, "mark_id_taken", "This mark id is already in use.")


@dataclass(frozen=True)
class DictationMark:
    """A mark the learner adds from the Dictation diff, placed by the dictation module.

    `at_ms` and `phrase` come from the scored diff, which the server made from the
    passage words, never from the browser.
    """

    id: uuid.UUID
    word_from: int
    word_to: int
    at_ms: int
    phrase: str


async def add_dictation_marks(
    db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID, marks: Sequence[DictationMark]
) -> list[schemas.Mark]:
    """Add marks from the Dictation diff (#55, FR-DI-6); one stored mark per entry, in order.

    The caller has checked that the session is the learner's and that these words were
    scored as missed or wrong. A new mark is `source = 'dictation'` and `suggested`, for
    the learner to confirm in Transcript (FR-TR-3). Words that are already marked, by
    either path, give back the mark they have, and a resend gives back the same mark, so
    adding twice never makes a duplicate. Refusals: 422 `mark_too_long`, 409
    `mark_id_taken` (the id belongs to other words).
    """
    added: list[schemas.Mark] = []
    for new in marks:
        try:
            check_length(new.word_from, new.word_to)
        except MarkRuleError as error:
            raise _refused(error) from error
        row = await repository.insert(
            db,
            repository.NewMark(
                id=new.id,
                session_id=session_id,
                user_id=learner,
                word_from=new.word_from,
                word_to=new.word_to,
                at_ms=new.at_ms,
                note=None,
                source="dictation",
                status="suggested",
            ),
        )
        if row is not None:
            await analytics.record_mark_created(db, learner, session_id, row.id, phrase=new.phrase)
        else:
            row = await _existing(db, session_id, new.id, new.word_from, new.word_to)
        added.append(_mark(row))
    return added


async def _existing(
    db: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID, word_from: int, word_to: int
) -> repository.MarkRow:
    """The mark a refused INSERT ran into: the same mark resent, or one on these words."""
    same = await repository.get(db, mark_id)
    if same and (same.session_id, same.word_from, same.word_to) == (session_id, word_from, word_to):
        return same
    if same is None and (other := await repository.find_range(db, session_id, word_from, word_to)):
        return other
    raise ProblemError(409, "mark_id_taken", "This mark id is already in use.")


async def session_marks(db: AsyncSession, session_id: uuid.UUID) -> list[schemas.Mark]:
    """The session's marks in audio order, for a caller that has authorized the session.

    The Dictation diff uses it to show which words are already added (#55).
    """
    return [_mark(row) for row in await repository.list_for_session(db, session_id)]


async def change_note(
    db: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID, note: str | None
) -> schemas.Mark:
    """Replace the mark's note; an empty note removes it."""
    cleaned = _note(note)
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    row = await repository.set_note(db, session_id, mark_id, cleaned)
    if row is None:
        raise _mark_not_found()
    return _mark(row)


async def confirm_mark(db: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID) -> schemas.Mark:
    """FR-TR-3: the learner confirms a suggested Dictation mark; a confirmed one stays so."""
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    row = await repository.confirm(db, session_id, mark_id)
    if row is None:
        raise _mark_not_found()
    return _mark(row)


async def remove_mark(db: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID) -> None:
    """Delete the mark, from either source: a removed Dictation suggestion is not kept
    (ADR 0056)."""
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    if not await repository.delete(db, session_id, mark_id):
        raise _mark_not_found()


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    """The learner's marks for their data export (#92)."""
    return ExportPart(
        tables=(await learner_rows(session, "practice.marks", learner, order_by="created_at"),)
    )
