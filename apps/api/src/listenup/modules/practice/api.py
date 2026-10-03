"""HTTP routes of the practice module (Architecture 9.2: Sessions; issue #48).

The rules live in `service.py` and `domain/plan.py`; these routes only translate.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.identity.service import CurrentLearner
from listenup.modules.practice import schemas, service
from listenup.modules.practice.service import PracticeSession
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["sessions"])


def _session(practice: PracticeSession, title: str) -> schemas.Session:
    return schemas.Session(
        id=practice.id,
        content_id=practice.content_id,
        content_title=title,
        passage=schemas.PassageRange(
            start_ms=practice.passage.start_ms, end_ms=practice.passage.end_ms
        ),
        entry=practice.entry,
        status=practice.status,
        version=practice.version,
        steps=[
            schemas.SessionStep(step=s.step, position=s.position, status=s.status)
            for s in practice.steps
        ],
        step_count=len(practice.steps),
        open_step=practice.open_step,
        open_position=practice.open_position,
        entry_locked=practice.entry_locked,
        entry_locked_at=practice.entry_locked_at,
        completed_at=practice.completed_at,
        created_at=practice.created_at,
        updated_at=practice.updated_at,
    )


async def _with_title(db: AsyncSession, practice: PracticeSession) -> schemas.Session:
    titles = await content.content_titles(db, [practice.content_id])
    return _session(practice, titles.get(practice.content_id, ""))


@router.post(
    "/sessions",
    status_code=201,
    response_model=schemas.Session,
    responses={
        404: {"description": "`content_not_found`"},
        409: {"description": "`content_not_ready`: the clip cannot be played yet"},
        422: {"description": "`invalid_passage`, `clip_too_short` or `passage_outside_clip`"},
    },
)
async def start_session(
    body: schemas.StartSession,
    request: Request,
    learner: CurrentLearner,
    db: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Start a plan on a clip from the library, with its first step open (FR-PL-1, FR-LB-2).

    The clip must be playable, and the passage 30 s to 15 min long and within the clip.
    An `Idempotency-Key` makes a retry return the first session instead of a second one.
    """

    async def start() -> tuple[int, Any]:
        practice = await service.start_plan(
            db,
            learner,
            body.content_id,
            body.passage.start_ms,
            body.passage.end_ms,
            body.entry,
        )
        return 201, (await _with_title(db, practice)).model_dump(mode="json")

    return await run_once(db, learner, idempotency_key, await request_fingerprint(request), start)


@router.get("/sessions")
async def list_sessions(
    learner: CurrentLearner,
    db: DbSession,
    response: Response,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = service.PAGE_SIZE,
) -> schemas.SessionList:
    """The learner's sessions, most recently active first, in keyset pages."""
    page = await service.list_sessions(db, learner, cursor, limit)
    titles = await content.content_titles(db, [p.content_id for p in page.items])
    response.headers["Cache-Control"] = "private, no-cache"
    return schemas.SessionList(
        items=[_session(p, titles.get(p.content_id, "")) for p in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/sessions/{session_id}", responses={404: {"description": "`session_not_found`"}})
async def get_session(
    session_id: uuid.UUID, learner: CurrentLearner, db: DbSession, response: Response
) -> schemas.Session:
    """One session with its plan: steps, the open step and the entry lock."""
    practice = await service.get_session(db, session_id)
    response.headers["Cache-Control"] = "private, no-cache"
    return await _with_title(db, practice)
