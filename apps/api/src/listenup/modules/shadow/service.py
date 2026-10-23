"""Shadow entry and segment selection (FR-SH-1, D8); no recording or rounds."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.practice import service as practice
from listenup.modules.review import service as review
from listenup.modules.shadow import repository, schemas
from listenup.modules.shadow.domain.segment import propose, validate
from listenup.modules.shadow.models import ShadowSegment
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
    await repository.lock_session(db, session_id)
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
        )
    )
