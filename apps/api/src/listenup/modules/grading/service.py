"""Queue shared passage references; gist grading is a separate story (#67)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.platform.errors import ProblemError
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
