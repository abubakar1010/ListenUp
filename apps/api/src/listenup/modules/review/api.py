"""Transcript step HTTP boundary (FR-TR-1, FR-TR-2, FR-TX-5)."""

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

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


_NO_STORE = {"Cache-Control": "private, no-store"}
_GATE: dict[int | str, dict[str, Any]] = {
    401: {"description": "`not_signed_in`"},
    404: {"description": "`session_not_found`"},
    409: {"description": "`step_locked`"},
}


@router.get("/sessions/{session_id}/marks", responses=_GATE)
async def list_marks(
    session_id: uuid.UUID, response: Response, learner: CurrentLearner, db: DbSession
) -> schemas.MarkList:
    """The session's marks in audio order (NFR-REL-1: they come back after a reload)."""
    response.headers.update(_NO_STORE)
    return schemas.MarkList(marks=await service.list_marks(db, session_id))


@router.post(
    "/sessions/{session_id}/marks",
    status_code=201,
    response_model=schemas.Mark,
    responses={
        **_GATE,
        200: {"model": schemas.Mark, "description": "The same mark, sent again"},
        409: {
            "description": "`step_locked`, `transcript_not_ready`, `transcript_failed`, "
            "`mark_exists` (with `mark_id`) or `mark_id_taken`"
        },
        422: {"description": "`mark_out_of_range`, `mark_too_long` or `note_too_long`"},
    },
)
async def create_mark(
    session_id: uuid.UUID,
    body: schemas.NewMark,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
) -> JSONResponse:
    """Mark a word or phrase (FR-TR-2). The browser names the mark with a new id, so
    a create resent after a lost connection answers 200 with the stored mark instead
    of making a second one (ADR 0047). The server sets the audio time from the words.
    """
    mark, created = await service.create_mark(
        db, request.app.state.transcript_database, learner, session_id, body
    )
    return JSONResponse(
        mark.model_dump(mode="json"), status_code=201 if created else 200, headers=_NO_STORE
    )


@router.patch(
    "/sessions/{session_id}/marks/{mark_id}",
    responses={
        **_GATE,
        404: {"description": "`session_not_found` or `mark_not_found`"},
        422: {"description": "`note_too_long`"},
    },
)
async def change_mark_note(
    session_id: uuid.UUID,
    mark_id: uuid.UUID,
    body: schemas.MarkNote,
    response: Response,
    learner: CurrentLearner,
    db: DbSession,
) -> schemas.Mark:
    """Replace the mark's note; an empty or null note removes it."""
    response.headers.update(_NO_STORE)
    return await service.change_note(db, session_id, mark_id, body.note)


@router.delete(
    "/sessions/{session_id}/marks/{mark_id}",
    status_code=204,
    responses={**_GATE, 404: {"description": "`session_not_found` or `mark_not_found`"}},
)
async def remove_mark(
    session_id: uuid.UUID, mark_id: uuid.UUID, learner: CurrentLearner, db: DbSession
) -> None:
    """Remove the mark. A second removal answers 404 `mark_not_found`."""
    await service.remove_mark(db, session_id, mark_id)
