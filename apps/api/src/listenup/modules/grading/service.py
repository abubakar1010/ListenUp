"""Queue private gist grading and shared passage references (FR-BL-6/14)."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.grading import repository
from listenup.modules.practice import service as practice
from listenup.platform.clock import server_now
from listenup.platform.config import get_settings
from listenup.platform.database import Database
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


async def queue_gist(
    db: AsyncSession, learner: uuid.UUID, attempt_id: uuid.UUID, now: datetime | None = None
) -> None:
    """Submission and pending result/job commit together; inference never runs here."""
    # API processes register the handler before enqueue, as the transcript service does.
    from listenup.modules.grading.jobs import GRADE_GIST_JOB

    deadline = (now or server_now()) + timedelta(
        seconds=get_settings().gist_feedback_timeout_seconds
    )
    await repository.ensure_pending(db, learner, attempt_id, deadline)
    key = f"gist-grade:{attempt_id}"
    await enqueue(
        db,
        GRADE_GIST_JOB,
        unique_key=key,
        lock=key,
        attempt_id=str(attempt_id),
        user_id=str(learner),
    )
    await queue_deadline(db, learner, attempt_id, deadline)


async def queue_deadline(
    db: AsyncSession, learner: uuid.UUID, attempt_id: uuid.UUID, deadline: datetime
) -> None:
    await enqueue(
        db,
        "grading.gist_deadline",
        unique_key=f"gist-deadline:{attempt_id}:{deadline.isoformat()}",
        run_at=deadline,
        attempt_id=str(attempt_id),
        user_id=str(learner),
        deadline=deadline.isoformat(),
    )


async def export_data(db: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(tables=(await learner_rows(db, "grading.gist_grades", learner),))


async def read_gist_grade(
    db: AsyncSession,
    references: Database,
    learner: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    reveal_details: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read this learner's stored grade; never return reference hints through D4.

    Blind authorizes the submitted attempt and derives reveal_details from the plan.
    The shared reference is read by its stored FK, never by caller-provided media ids.
    No API-role cache grant is needed (ADR 0054).
    """
    now = now or server_now()
    await repository.expire_feedback(db, learner, attempt_id, now)
    grade = await repository.grade(db, learner, attempt_id)
    if grade is None:
        return {"status": "pending"}
    if grade.status != "ready":
        waiting: dict[str, Any] = {"status": grade.status}
        if grade.status == "pending":
            waiting["wait_ms"] = max(0, int((grade.feedback_deadline - now).total_seconds() * 1000))
        return waiting
    if grade.key_points_id is None:
        return {"status": "unavailable"}
    async with references.transaction() as reference_db:
        points = await repository.points_by_id(reference_db, grade.key_points_id)
    if points is None:
        return {"status": "pending"}
    covered = set(grade.covered_points or [])
    result: dict[str, Any] = {
        "status": "ready",
        "overall": grade.overall,
        "level": grade.level,
        "dimension_scores": grade.dimension_scores,
        "captured_count": sum(point["id"] in covered for point in points),
        "total_count": len(points),
    }
    if reveal_details:
        result.update(
            feedback=grade.feedback,
            key_points=[
                {"text": point["text"], "captured": point["id"] in covered} for point in points
            ],
        )
    return result


async def retry_gist(
    db: AsyncSession, learner: uuid.UUID, attempt_id: uuid.UUID, now: datetime
) -> bool:
    """Authorize in Blind; return whether reference work may need recovery.

    Lock feedback through queue admission; an existing grading job still needs
    its reference dependency to be retryable without duplicating grading.
    """
    from sqlalchemy import select

    from listenup.modules.grading.jobs import GRADE_GIST_JOB
    from listenup.modules.grading.models import GistGrade

    row = await db.scalar(
        select(GistGrade)
        .where(GistGrade.attempt_id == attempt_id, GistGrade.user_id == learner)
        .with_for_update()
    )
    if row is None:
        raise ProblemError(404, "grade_not_found", "There is no such grade.")
    if row.status == "ready":
        return False
    key = f"gist-grade:{attempt_id}"
    queued = await enqueue(
        db,
        GRADE_GIST_JOB,
        unique_key=key,
        lock=key,
        attempt_id=str(attempt_id),
        user_id=str(learner),
    )
    if queued is None:
        return True
    row.status = "pending"
    row.feedback_deadline = now + timedelta(seconds=get_settings().gist_feedback_timeout_seconds)
    row.updated_at = now
    await queue_deadline(db, learner, attempt_id, row.feedback_deadline)
    return True
