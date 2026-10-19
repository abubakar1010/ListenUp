"""Transcript step HTTP boundary (FR-TR-1, FR-TX-5)."""

import uuid

from fastapi import APIRouter, Request, Response

from listenup.modules.identity.service import CurrentLearner
from listenup.modules.review import schemas, service
from listenup.platform.database import DbSession

router = APIRouter(tags=["review"])


@router.get(
    "/sessions/{session_id}/transcript",
    responses={
        401: {"description": "`not_signed_in`"},
        404: {"description": "`session_not_found` or `content_not_found`"},
        409: {"description": "`step_locked`, `transcript_not_ready` or `transcript_failed`"},
    },
)
async def read_transcript(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    learner: CurrentLearner,
    db: DbSession,
) -> schemas.TranscriptReview:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.read_transcript(
        db, request.app.state.transcript_database, learner, session_id
    )
