"""Shadow segment and playback HTTP boundary (FR-SH-1/2/3)."""

import uuid

from fastapi import APIRouter, Request, Response

from listenup.modules.identity.service import CurrentLearner
from listenup.modules.practice import service as practice
from listenup.modules.shadow import schemas, service
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["shadow"])
_ROUND_ERRORS: dict[int | str, dict[str, str]] = {
    404: {"description": "`session_not_found`"},
    409: {"description": "`step_locked`, `session_closed`, `round_order` or `round_limit`"},
}


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


@router.get(
    "/sessions/{session_id}/shadow/rounds",
    response_model_exclude_unset=True,
    responses=_ROUND_ERRORS,
)
async def read_rounds(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    learner: CurrentLearner,
    db: DbSession,
) -> schemas.Rounds:
    response.headers["Cache-Control"] = "private, no-store"
    return await service.round_state(db, session_id, request.app.state.transcript_database, learner)


async def mutate_round(
    session_id: uuid.UUID,
    number: int,
    request: Request,
    learner: uuid.UUID,
    db: DbSession,
    key: str | None,
    *,
    ended: bool,
) -> Response:
    # Gate even idempotent replays; never store transcript-bearing responses.
    await practice.lock_session(db, session_id)
    await practice.require_step(db, session_id, practice.Step.SHADOW)

    async def apply() -> tuple[int, None]:
        await service.change_round(db, session_id, number, ended=ended)
        return 204, None

    result = await run_once(db, learner, key, await request_fingerprint(request), apply)
    return Response(
        status_code=result.status_code,
        headers={**result.headers, "Cache-Control": "private, no-store"},
    )


@router.post(
    "/sessions/{session_id}/shadow/rounds/{number}/start",
    status_code=204,
    response_class=Response,
    responses=_ROUND_ERRORS,
)
async def start_round(
    session_id: uuid.UUID,
    number: int,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> Response:
    return await mutate_round(
        session_id, number, request, learner, db, idempotency_key, ended=False
    )


@router.post(
    "/sessions/{session_id}/shadow/rounds/{number}/playback-ended",
    status_code=204,
    response_class=Response,
    responses=_ROUND_ERRORS,
)
async def end_playback(
    session_id: uuid.UUID,
    number: int,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> Response:
    return await mutate_round(session_id, number, request, learner, db, idempotency_key, ended=True)
