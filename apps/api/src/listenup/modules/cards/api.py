"""Cards HTTP boundary (#72)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from listenup.modules.cards import schemas, service
from listenup.modules.content.service import UploadsDep
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["cards"])
_NO_STORE = {"Cache-Control": "private, no-store"}


@router.post(
    "/sessions/{session_id}/cards",
    status_code=201,
    response_model=schemas.Card,
    responses={
        401: {"description": "`not_signed_in`"},
        404: {"description": "`session_not_found` or `mark_not_found`"},
        409: {"description": "`step_locked` or `card_limit_reached`"},
    },
)
async def create_card(
    session_id: uuid.UUID,
    body: schemas.NewCard,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    async def create() -> tuple[int, Any]:
        return 201, (
            await service.create(
                db, learner, session_id, body, request.app.state.transcript_database
            )
        ).model_dump(mode="json")

    result = await run_once(
        db, learner, idempotency_key, await request_fingerprint(request), create
    )
    result.headers.update(_NO_STORE)
    return result


@router.get("/cards")
async def list_cards(
    response: Response,
    learner: CurrentLearner,
    db: DbSession,
    session_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> schemas.CardList:
    response.headers.update(_NO_STORE)
    return await service.list_cards(db, session_id, cursor, limit)


@router.delete(
    "/cards/{card_id}", status_code=204, responses={404: {"description": "`card_not_found`"}}
)
async def delete_card(card_id: uuid.UUID, learner: CurrentLearner, db: DbSession) -> None:
    await service.delete(db, card_id)


@router.post("/sessions/{session_id}/cards/complete", status_code=204, response_class=Response)
async def complete_cards(
    session_id: uuid.UUID,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> Response:
    async def complete() -> tuple[int, Any]:
        await service.complete(db, session_id)
        return 204, None

    result = await run_once(
        db, learner, idempotency_key, await request_fingerprint(request), complete
    )
    return Response(status_code=result.status_code, headers={**result.headers, **_NO_STORE})


@router.get(
    "/cards/{card_id}/audio",
    response_class=RedirectResponse,
    status_code=307,
    responses={
        404: {"description": "`card_not_found`"},
        409: {"description": "`card_audio_not_ready`"},
    },
)
async def card_audio(
    card_id: uuid.UUID, learner: CurrentLearner, db: DbSession, uploads: UploadsDep
) -> RedirectResponse:
    return RedirectResponse(
        await service.audio_url(db, uploads.storage, learner, card_id),
        status_code=307,
        headers=_NO_STORE,
    )


@router.post(
    "/cards/{card_id}/audio/retry",
    status_code=202,
    response_class=Response,
    responses={
        404: {"description": "`card_not_found`"},
        409: {"description": "`card_audio_not_failed`"},
    },
)
async def retry_audio(card_id: uuid.UUID, learner: CurrentLearner, db: DbSession) -> Response:
    await service.retry_audio(db, learner, card_id)
    return Response(status_code=202, headers=_NO_STORE)
