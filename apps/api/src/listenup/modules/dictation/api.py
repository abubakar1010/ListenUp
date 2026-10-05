"""HTTP routes of the dictation module (Architecture 9.2: Dictation; #51, #52, ADR 0025).

The rules live in `service.py`; these routes only translate. Submission and scoring
(`POST /dictation/attempts/{id}/submit`, #53 and #54) are not built yet.
"""

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from listenup.modules.dictation import schemas, service
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession

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
