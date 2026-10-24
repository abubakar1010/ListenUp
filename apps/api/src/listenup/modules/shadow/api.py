"""Shadow segment HTTP boundary (FR-SH-1)."""

import uuid

from fastapi import APIRouter, Response

from listenup.modules.identity.service import CurrentLearner
from listenup.modules.shadow import schemas, service
from listenup.platform.database import DbSession

router = APIRouter(tags=["shadow"])


@router.get(
    "/sessions/{session_id}/shadow/segment",
    responses={404: {"description": "`session_not_found`"}, 409: {"description": "`step_locked`"}},
)
async def read_segment(
    session_id: uuid.UUID, response: Response, learner: CurrentLearner, db: DbSession
) -> schemas.Segment:
    """Resume the saved selection, proposing one on first entry."""
    response.headers["Cache-Control"] = "private, no-store"
    return await service.segment(db, session_id)


@router.put(
    "/sessions/{session_id}/shadow/segment",
    responses={
        404: {"description": "`session_not_found`"},
        409: {"description": "`step_locked` or `segment_locked`"},
        422: {"description": "`segment_span` or `validation_failed`"},
    },
)
async def choose_segment(
    session_id: uuid.UUID,
    body: schemas.SegmentChoice,
    response: Response,
    learner: CurrentLearner,
    db: DbSession,
) -> schemas.Segment:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.segment(db, session_id, body)
