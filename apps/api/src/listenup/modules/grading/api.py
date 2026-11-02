"""Owned round evidence availability and retry (FR-SH-16, E2)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, TypeAdapter

from listenup.modules.grading import service
from listenup.modules.identity.service import CurrentLearner, require_voice_consent
from listenup.platform.database import DbSession

router = APIRouter(tags=["grading"])


class RoundFeedbackUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"


class MeasureScore(BaseModel):
    """0 to 100, or null with the reason it could not be observed."""

    score: int | None = Field(ge=0, le=100)
    reason: str | None


class ScoredMeasures(BaseModel):
    timing: MeasureScore
    pronunciation: MeasureScore
    articulation: MeasureScore
    fluency: MeasureScore
    fillers: MeasureScore
    completeness: MeasureScore


class AccentGuidance(BaseModel):
    """Guidance compared with this speaker, never correctness, and not in the
    overall score (FR-SH-15, D11, UX-33)."""

    score: int | None = Field(ge=0, le=100)
    reason: str | None
    experimental: bool
    compared_with: Literal["this_speaker"]
    in_overall: Literal[False]


class SoundReason(BaseModel):
    sound: str
    position: Literal["initial", "medial", "final"]
    issue: Literal["dropped", "merged", "unclear", "inaccurate"]
    linking: bool


class WordLabel(BaseModel):
    """One segment word's marker (FR-SH-10); missed words have no score."""

    index: int = Field(ge=0)
    text: str
    label: Literal["good", "needs_work", "missed"]
    score: int | None = Field(ge=0, le=100)
    reasons: list[SoundReason]


class RoundFeedbackScored(BaseModel):
    status: Literal["scored"]
    overall: int = Field(ge=0, le=100)
    measures: ScoredMeasures
    accent: AccentGuidance
    word_labels: list[WordLabel]


RoundFeedback = Annotated[
    RoundFeedbackUnavailable | RoundFeedbackScored, Field(discriminator="status")
]


_FEEDBACK: TypeAdapter[RoundFeedbackUnavailable | RoundFeedbackScored] = TypeAdapter(RoundFeedback)


class RetryAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"


@router.get("/shadow/rounds/{round_id}/grade", responses={404: {"description": "round_not_found"}})
async def read_round(
    round_id: uuid.UUID, learner: CurrentLearner, db: DbSession, response: Response
) -> RoundFeedback:
    response.headers["Cache-Control"] = "private, no-store"
    return _FEEDBACK.validate_python(await service.read_round_grade(db, learner, round_id))


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
