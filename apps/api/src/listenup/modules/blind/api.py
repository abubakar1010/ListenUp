"""HTTP routes of the blind module (Architecture 9.2: Blind; issues #62, #63, #65).

The rules live in `domain/` and `service.py`; these routes only translate. Time is
the server's (`server_now`), never the browser's.
"""

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from listenup.modules.blind import schemas, service
from listenup.modules.blind.domain import (
    HEARTBEAT_INTERVAL_MS,
    RESUME_DELAY_MS,
    Beat,
    VoidReason,
)
from listenup.modules.content.service import UploadsDep
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["blind"])


def server_now() -> datetime:
    """The server's clock; tests override this dependency."""
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(server_now)]


def _attempt(view: service.BlindAttempt) -> schemas.BlindAttempt:
    return schemas.BlindAttempt.model_validate(dataclasses.asdict(view))


def _media_path(attempt_id: uuid.UUID, token: str) -> str:
    return f"/api/v1/blind/attempts/{attempt_id}/media/{token}"


@router.get(
    "/sessions/{session_id}/blind",
    responses={
        404: {"description": "`session_not_found`"},
        409: {"description": "`step_locked` or `step_not_in_plan`"},
    },
)
async def get_blind_step(
    session_id: uuid.UUID, learner: CurrentLearner, db: DbSession, response: Response
) -> schemas.BlindStep:
    """The Blind step with its newest attempt, so a reloaded page knows where it stands."""
    step = await service.get_step(db, session_id)
    response.headers["Cache-Control"] = "private, no-store"
    return schemas.BlindStep(
        session_id=step.session_id,
        passage_start_ms=step.passage_start_ms,
        passage_end_ms=step.passage_end_ms,
        step_status=step.step_status,
        attempt=_attempt(step.attempt) if step.attempt else None,
    )


@router.post(
    "/sessions/{session_id}/blind/attempts",
    status_code=201,
    responses={
        404: {"description": "`session_not_found`"},
        409: {"description": "`step_locked`, or `attempt_active` with `attempt_id`"},
    },
)
async def start_attempt(
    session_id: uuid.UUID, learner: CurrentLearner, db: DbSession, now: Now, response: Response
) -> schemas.StartedAttempt:
    """Start one listen of the passage (FR-BL-1, #62).

    Returns a media URL bound to this attempt. The player sends a heartbeat every
    `heartbeat_interval_ms` from now on.
    """
    started = await service.start(db, session_id, now)
    response.headers["Cache-Control"] = "private, no-store"
    return schemas.StartedAttempt(
        attempt=_attempt(started.attempt),
        media_url=_media_path(started.attempt.id, started.media_token),
        heartbeat_interval_ms=HEARTBEAT_INTERVAL_MS,
        resume_delay_ms=RESUME_DELAY_MS,
    )


@router.post(
    "/blind/attempts/{attempt_id}/heartbeat",
    responses={404: {"description": "`attempt_not_found`"}},
)
async def heartbeat(
    attempt_id: uuid.UUID,
    body: schemas.HeartbeatIn,
    learner: CurrentLearner,
    db: DbSession,
    now: Now,
) -> schemas.HeartbeatOut:
    """Report the player's position every 5 s (FR-BL-3, System Design 9.2).

    The answer is `continue`, `resume` (the one resume after an interruption the
    learner did not cause, D13 and D18) or `stop` with the attempt's `void_reason`.
    """
    beat = Beat(**body.model_dump())
    result = await service.heartbeat(db, attempt_id, beat, now)
    return schemas.HeartbeatOut(
        action=result.action,
        attempt=_attempt(result.attempt),
        resume_from_ms=result.resume_from_ms,
        resume_delay_ms=RESUME_DELAY_MS,
    )


@router.post(
    "/blind/attempts/{attempt_id}/void",
    responses={404: {"description": "`attempt_not_found`"}},
)
async def void_attempt(
    attempt_id: uuid.UUID, body: schemas.VoidIn, learner: CurrentLearner, db: DbSession
) -> schemas.BlindAttempt:
    """The page reports leaving, a reload or a seek: the listen ends (FR-BL-3).

    Sent with `fetch(..., {keepalive: true})` from `pagehide` and `visibilitychange`.
    After the whole passage has played it changes nothing.
    """
    return _attempt(await service.void(db, attempt_id, VoidReason(body.reason)))


@router.get(
    "/blind/attempts/{attempt_id}/media/{token}",
    response_class=RedirectResponse,
    status_code=307,
    responses={
        307: {"description": "Redirect to a signed storage URL that ends with the attempt"},
        404: {"description": "`attempt_not_found` or `media_not_found` (wrong token)"},
        409: {"description": "`media_not_ready`"},
        410: {"description": "`media_expired`: the attempt ended or its window is over"},
    },
)
async def attempt_media(
    attempt_id: uuid.UUID,
    token: Annotated[str, Path(max_length=200)],
    learner: CurrentLearner,
    db: DbSession,
    uploads: UploadsDep,
    now: Now,
) -> RedirectResponse:
    """The passage's audio for this attempt only (#62). Range requests go to storage.

    The token in the path comes from starting the attempt; the redirect's signed URL
    lives only until the attempt's window ends.
    """
    url = await service.media_url(db, uploads.storage, learner, attempt_id, token, now)
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, no-store"})


@router.post(
    "/blind/attempts/{attempt_id}/gist",
    status_code=201,
    response_model=schemas.GistSubmitted,
    responses={
        404: {"description": "`attempt_not_found`"},
        409: {"description": "`listen_incomplete`, `attempt_closed` or `step_locked`"},
        422: {"description": "`gist_too_short` (with `sentences`) or `gist_too_long`"},
    },
)
async def submit_gist(
    attempt_id: uuid.UUID,
    body: schemas.GistIn,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    now: Now,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Submit the three-sentence gist after the whole passage has played (FR-BL-4, #65).

    Completes the Blind step. An `Idempotency-Key` makes a retry return the first answer.
    """

    async def submit() -> tuple[int, Any]:
        done = await service.submit_gist(db, attempt_id, body.text, now)
        out = schemas.GistSubmitted(
            attempt=_attempt(done.attempt),
            open_step=done.open_step,
            session_version=done.session_version,
        )
        return 201, out.model_dump(mode="json")

    return await run_once(db, learner, idempotency_key, await request_fingerprint(request), submit)
