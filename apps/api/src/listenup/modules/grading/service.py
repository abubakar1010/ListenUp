"""Queue private gist grading and shared passage references (FR-BL-6/14)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.grading import repository
from listenup.modules.practice import service as practice
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows
from listenup.platform.jobs import enqueue

EXTRACT_KEY_POINTS = "grading.extract_key_points"


async def on_transcript_ready(db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID) -> None:
    """Authorize in the learner transaction, then enqueue ids and bounds only.

    Work belongs to the media, so deleting the triggering session/account cannot
    cancel a reference another learner needs. The queue lock covers inference through
    commit; the handler rechecks the persistent cache after taking it (ADR 0036).
    """
    session = await practice.get_session(db, session_id)
    if session.user_id != learner:
        raise ProblemError(404, "session_not_found", "There is no such session.")
    item = await content.get_content(db, learner, session.content_id)
    left, right = session.passage.start_ms, session.passage.end_ms
    key = f"key-points:{item.media_object_id}:{left}:{right}"
    await enqueue(
        db,
        EXTRACT_KEY_POINTS,
        unique_key=key,
        lock=key,
        media_id=str(item.media_object_id),
        start_ms=left,
        end_ms=right,
    )


GRADE_GIST = "grading.grade_gist"


async def queue_gist(db: AsyncSession, learner: uuid.UUID, attempt_id: uuid.UUID) -> None:
    """Submission and pending result/job commit together; inference never runs here."""
    # API processes register the handler before enqueue, as the transcript service does.
    from listenup.modules.grading.jobs import GRADE_GIST_JOB

    await repository.ensure_pending(db, learner, attempt_id)
    key = f"gist-grade:{attempt_id}"
    await enqueue(
        db,
        GRADE_GIST_JOB,
        unique_key=key,
        lock=key,
        attempt_id=str(attempt_id),
        user_id=str(learner),
    )


async def export_data(db: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(tables=(await learner_rows(db, "grading.gist_grades", learner),))
