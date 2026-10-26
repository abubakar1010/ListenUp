"""Shadow segment selection and playback rounds; recording is #81."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.practice import service as practice
from listenup.modules.review import service as review
from listenup.modules.shadow import repository, schemas
from listenup.modules.shadow.domain.segment import propose, validate
from listenup.modules.shadow.models import ShadowSegment
from listenup.modules.transcript import service as transcript
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows


def present(row: ShadowSegment) -> schemas.Segment:
    assert row.span.lower is not None and row.span.upper is not None
    return schemas.Segment(
        session_id=row.session_id,
        start_ms=row.span.lower,
        end_ms=row.span.upper,
        chosen_by=row.chosen_by,
        mark_count=row.mark_count,
        locked_at=row.locked_at,
    )


async def segment(
    db: AsyncSession, session_id: uuid.UUID, choice: schemas.SegmentChoice | None = None
) -> schemas.Segment:
    await practice.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.SHADOW)
    row = await repository.get(db, session_id)
    if choice is None and row is not None:
        return present(row)
    if row is not None and row.locked_at is not None:
        raise ProblemError(409, "segment_locked", "The segment is fixed once round 1 starts.")
    p = session.passage
    marks = [m.at_ms for m in await review.list_marks(db, session_id)]
    if choice is None:
        start, end, count = propose(p.start_ms, p.end_ms, marks)
    else:
        start, end = choice.start_ms, choice.end_ms
        try:
            validate(p.start_ms, p.end_ms, start, end)
        except ValueError as error:
            raise ProblemError(
                422,
                "segment_span",
                "Choose 60 to 90 seconds, or the whole passage when it is under 60 seconds.",
            ) from error
        count = sum(start <= m < end for m in marks)
    return present(
        await repository.save(
            db,
            session_id,
            session.user_id,
            start,
            end,
            count,
            "system" if choice is None else "learner",
        )
    )


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(
        tables=(
            await learner_rows(session, "practice.shadow_segments", learner, order_by="session_id"),
            await learner_rows(session, "practice.shadow_rounds", learner, order_by="created_at"),
        )
    )


async def round_state(
    db: AsyncSession, session_id: uuid.UUID, worker_database: Database, learner: uuid.UUID
) -> schemas.Rounds:
    selection = await segment(db, session_id)
    rows = await repository.rounds(db, session_id)
    summaries = [
        schemas.Round(
            round=r.round,
            transcript_shown=r.transcript_shown,
            playback_status=r.playback_status,
            recorded_at=r.recorded_at,
        )
        for r in rows
    ]
    state = schemas.Rounds(
        segment=selection, current=summaries[-1] if summaries else None, rounds=summaries
    )
    if state.current is not None and state.current.round == 1:
        words = await transcript.read_passage(db, worker_database, learner, session_id)
        state.text = " ".join(
            word
            for word, at in zip(words.words, words.start_ms, strict=True)
            if selection.start_ms <= at < selection.end_ms
        )
    return state


async def change_round(
    db: AsyncSession, session_id: uuid.UUID, number: int, *, ended: bool = False
) -> None:
    await practice.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.SHADOW)
    if number > 3:
        raise ProblemError(409, "round_limit", "Shadow has only three rounds.")
    await segment(db, session_id)
    rows = await repository.rounds(db, session_id)
    current = rows[-1] if rows else None
    if ended:
        if current is None or current.round != number:
            raise ProblemError(409, "round_order", "End the current round only.")
        current.playback_status = "ended"
        await db.flush()
        return
    if current is not None and current.round == number:
        return
    if (
        number < 1
        or number != (current.round + 1 if current else 1)
        or (current is not None and current.playback_status != "ended")
    ):
        raise ProblemError(409, "round_order", "Play the three rounds in order.")
    await repository.insert_round(db, session_id, session.user_id, number)
