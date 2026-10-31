"""Owned round evidence availability and retry (FR-SH-16, E2)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from listenup.modules.grading import service
from listenup.modules.identity.service import CurrentLearner, require_voice_consent
from listenup.platform.database import DbSession

router = APIRouter(tags=["grading"])


class RoundFeedback(BaseModel):
    status: Literal["unavailable"] = "unavailable"


class RetryAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"


@router.get("/shadow/rounds/{round_id}/grade", responses={404: {"description": "round_not_found"}})
async def read_round(
    round_id: uuid.UUID, learner: CurrentLearner, db: DbSession, response: Response
) -> RoundFeedback:
    response.headers["Cache-Control"] = "private, no-store"
    return RoundFeedback.model_validate(await service.read_round_grade(db, learner, round_id))


@router.post(
    "/shadow/rounds/{round_id}/grade/retry",
    status_code=202,
    responses={404: {"description": "round_not_found"}},
)
async def retry_round(
    round_id: uuid.UUID,
    learner: CurrentLearner,
    db: DbSession,
    request: Request,
    response: Response,
) -> RetryAccepted:
    from listenup.modules.shadow import service as shadow

    await shadow.require_owned_round(db, learner, round_id)
    await require_voice_consent(db, learner, request.app.state.settings)
    await service.retry_round(db, learner, round_id)
    response.headers["Cache-Control"] = "private, no-store"
    return RetryAccepted()
