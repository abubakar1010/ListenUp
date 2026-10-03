"""HTTP routes of the content module (Architecture 9.2: Intake)."""

import dataclasses
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from listenup.modules.content import schemas, service
from listenup.modules.content.service import UploadsDep
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["content"])


@router.get("/uploads/usage")
async def upload_usage(
    learner: CurrentLearner, session: DbSession, uploads: UploadsDep
) -> schemas.StorageUse:
    """How much of the per-account upload storage is used, and the per-file limit (D5)."""
    return schemas.StorageUse(**dataclasses.asdict(await uploads.usage(session, learner)))


@router.post("/uploads", status_code=201)
async def start_upload(
    body: schemas.UploadRequest,
    learner: CurrentLearner,
    session: DbSession,
    uploads: UploadsDep,
) -> schemas.UploadTarget:
    """Check the declared file and return a signed URL to PUT it straight to storage.

    Refused before any byte is sent: an unsupported type (`unsupported_file_type`), a
    file over the size limit (`file_too_large`), or one that would take the account
    over its storage cap (`storage_full`). Rate-limited per learner.
    """
    started = await uploads.start(
        session, learner, body.filename, body.content_type, body.size_bytes
    )
    return schemas.UploadTarget(
        upload_id=started.upload_id,
        url=started.url,
        method="PUT",
        headers=started.headers,
        expires_at=started.expires_at,
    )


@router.delete("/uploads/{upload_id}", status_code=204)
async def cancel_upload(
    upload_id: uuid.UUID, learner: CurrentLearner, session: DbSession, uploads: UploadsDep
) -> None:
    """Forget an upload that was cancelled before it was added to the library."""
    await uploads.cancel(session, upload_id)


def _item(summary: service.ContentSummary) -> dict[str, Any]:
    return schemas.ContentItem.model_validate(dataclasses.asdict(summary)).model_dump(mode="json")


@router.post(
    "/contents",
    status_code=201,
    response_model=schemas.ContentItem,
    responses={200: {"model": schemas.ContentItem, "description": "Already confirmed"}},
)
async def add_content(
    body: schemas.ConfirmUpload,
    request: Request,
    learner: CurrentLearner,
    session: DbSession,
    uploads: UploadsDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Confirm an upload: the file must be in storage with the declared size.

    Creates a pending content item and queues its conversion. Confirming the same
    upload again returns the same item with 200; an `Idempotency-Key` replays the
    first response exactly.
    """

    async def confirm() -> tuple[int, Any]:
        confirmed = await uploads.confirm(session, learner, body.upload_id, body.title)
        return (201 if confirmed.created else 200), _item(confirmed.item)

    return await run_once(
        session, learner, idempotency_key, await request_fingerprint(request), confirm
    )


@router.get("/contents")
async def list_contents(
    learner: CurrentLearner,
    session: DbSession,
    response: Response,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = service.PAGE_SIZE,
) -> schemas.ContentList:
    """The learner's content items, newest first, in keyset pages."""
    page = await service.list_contents(session, learner, cursor, limit)
    response.headers["Cache-Control"] = "private, no-cache"
    return schemas.ContentList(
        items=[schemas.ContentItem.model_validate(dataclasses.asdict(i)) for i in page.items],
        next_cursor=page.next_cursor,
    )
