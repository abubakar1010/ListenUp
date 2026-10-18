"""HTTP routes of the dictation module (Architecture 9.2: Dictation; #51, #52, ADR 0025).

The rules live in `service.py`; these routes only translate. Submission is
`POST /dictation/attempts/{id}/submit` (#54); the score arrives later (ADR 0041).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from listenup.modules.dictation import schemas, service
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["dictation"])


@router.post(
    "/sessions/{session_id}/dictation/attempts",
    status_code=201,
    response_model=schemas.DictationAttempt,
    responses={
        200: {"model": schemas.DictationAttempt, "description": "The live attempt, resumed"},
        404: {"description": "`session_not_found`"},
        409: {"description": "`step_locked`, `step_not_in_plan` or `session_closed`"},
    },
)
async def open_attempt(
    session_id: uuid.UUID, learner: CurrentLearner, db: DbSession
) -> JSONResponse:
    """Start the Dictation attempt (201), or resume the one in progress with its draft
    (200). Leaving or reloading never voids a Dictation attempt (FR-PL-6, NFR-REL-1).

    The answer holds what the player needs, the passage and the media path, and never
    any reference text (FR-DI-3, FR-TX-5).
    """
    work = await service.open_attempt(db, learner, session_id)
    body = schemas.DictationAttempt(
        id=work.attempt.id,
        session_id=work.attempt.session_id,
        status=work.attempt.status,
        started_at=work.attempt.started_at,
        resumed=work.resumed,
        draft_text=work.draft.text,
        draft_version=work.draft.version,
        draft_updated_at=work.draft.updated_at,
        passage=schemas.DictationPassage(
            start_ms=work.passage.start_ms, end_ms=work.passage.end_ms
        ),
        media_url=f"/api/v1/media/{work.media_object_id}",
    )
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=200 if work.resumed else 201,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/dictation/attempts/{attempt_id}/listen",
    status_code=204,
    responses={
        404: {"description": "`attempt_not_found`"},
        409: {"description": "`attempt_closed`, `step_locked` or `session_closed`"},
    },
)
async def record_listen_started(
    attempt_id: uuid.UUID, learner: CurrentLearner, db: DbSession
) -> None:
    """Record the attempt's first successful playback for the time-to-listen metric.

    Repeated calls are idempotent. Opening the Dictation screen alone records nothing.
    """
    await service.record_listen_started(db, attempt_id)


@router.put(
    "/dictation/attempts/{attempt_id}/draft",
    responses={
        404: {"description": "`attempt_not_found`"},
        409: {
            "description": "`draft_conflict` (with the current `draft_text` and "
            "`draft_version`), `attempt_closed`, `step_locked` or `session_closed`"
        },
        422: {"description": "`draft_too_long` (with `max_chars`)"},
    },
)
async def save_draft(
    attempt_id: uuid.UUID, body: schemas.SaveDraft, learner: CurrentLearner, db: DbSession
) -> schemas.SavedDraft:
    """Save the Dictation draft if it is still at `draft_version` (FR-DI-4, #50).

    A save based on an older version gets 409 `draft_conflict`, so two tabs never
    silently overwrite each other; resending a save that already landed succeeds.
    """
    draft = await service.save_draft(db, attempt_id, body.draft_text, body.draft_version)
    return schemas.SavedDraft(draft_version=draft.version, updated_at=draft.updated_at)


@router.post(
    "/dictation/attempts/{attempt_id}/submit",
    status_code=202,
    response_model=schemas.DictationSubmission,
    responses={
        404: {"description": "`attempt_not_found`"},
        409: {
            "description": "`step_locked`, `session_closed`, `session_changed` or `attempt_closed`"
        },
        422: {
            "description": "`empty_submission`, `submission_too_long` (with `max_chars`) "
            "or `idempotency_key_reused`"
        },
    },
)
async def submit(
    attempt_id: uuid.UUID,
    body: schemas.SubmitDictation,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Submit the text, finish the attempt and complete the Dictation step (FR-DI-5).

    The score is not in this answer: it is computed when the transcript is ready and
    announced by the `dictation.scored` event. An `Idempotency-Key` makes a retry
    return the first answer.
    """

    async def run() -> tuple[int, Any]:
        done = await service.submit(db, attempt_id, body.text, body.version, body.replay_count)
        out = schemas.DictationSubmission(
            attempt_id=done.attempt.id,
            status=done.attempt.status,
            scoring_status=done.scoring_status,  # type: ignore[arg-type]
        )
        return 202, out.model_dump(mode="json")

    response = await run_once(db, learner, idempotency_key, await request_fingerprint(request), run)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(
    "/dictation/attempts/{attempt_id}",
    response_model=schemas.DictationAttemptView,
    responses={404: {"description": "`attempt_not_found`"}},
)
async def get_attempt(
    attempt_id: uuid.UUID, learner: CurrentLearner, db: DbSession
) -> JSONResponse:
    """The attempt's state and, once scored, the diff and accuracy (FR-DI-5).

    The reference text is in `result.items` only. Before scoring it is in no answer
    of the Dictation routes (FR-DI-3, FR-TX-5). Refetch it when `dictation.scored`
    arrives on the event stream.
    """
    view = await service.get_attempt(db, attempt_id)
    body = schemas.DictationAttemptView(
        id=view.attempt.id,
        session_id=view.attempt.session_id,
        status=view.attempt.status,
        scoring_status=view.scoring_status,  # type: ignore[arg-type]
        result=None
        if view.result is None
        else schemas.DictationResult(
            accuracy=view.result.accuracy,
            counts=schemas.DiffCounts(**view.result.counts),
            items=[schemas.DiffItem(**vars(item)) for item in view.result.items],
        ),
    )
    return JSONResponse(
        body.model_dump(mode="json"), headers={"Cache-Control": "private, no-store"}
    )
