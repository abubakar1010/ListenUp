"""HTTP routes of the library module (Architecture 4.1, 9.2: Library).

The library owns no tables: it is read-only views over other modules, reached only
through their service.py.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from listenup.modules.content import service as content
from listenup.modules.identity.service import CurrentLearner
from listenup.modules.practice import service as practice
from listenup.platform.database import DbSession

router = APIRouter(tags=["library"])


class LibraryItem(BaseModel):
    id: uuid.UUID
    title: str
    source: Literal["upload", "youtube"]
    status: Literal["pending", "downloading", "playable", "failed", "expired"] = Field(
        description="Processing status of the clip's media"
    )
    duration_ms: int | None
    created_at: datetime
    last_session_status: practice.SessionStatus | None = Field(
        description="Status of the newest practice session on this item; null when none"
    )


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page")


@router.get(
    "/library/contents",
    response_model=LibraryPage,
    responses={304: {"description": "Not modified since the ETag in If-None-Match"}},
)
async def library_contents(
    request: Request,
    response: Response,
    learner: CurrentLearner,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=content.MAX_PAGE_SIZE)] = content.PAGE_SIZE,
) -> LibraryPage | Response:
    """The learner's library, newest first, 20 per page by default (FR-LB-1)."""
    page = await content.list_contents(session, learner, cursor, limit)
    last_status = await practice.latest_session_status(session, [item.id for item in page.items])
    body = LibraryPage(
        items=[
            LibraryItem(
                id=item.id,
                title=item.title,
                source=item.source,  # type: ignore[arg-type]
                status=item.status,  # type: ignore[arg-type]
                duration_ms=item.duration_ms,
                created_at=item.created_at,
                last_session_status=last_status.get(item.id),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
    # ETag responses (System Design 8.4): an unchanged page answers 304.
    etag = 'W/"' + hashlib.sha256(body.model_dump_json().encode()).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if etag in _etags(request.headers.get("if-none-match")):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return body


def _etags(header: str | None) -> set[str]:
    if not header:
        return set()
    return {tag.strip() for tag in header.split(",")}
