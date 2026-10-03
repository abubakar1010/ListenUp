"""HTTP routes of the content module (Architecture 9.2: Intake)."""

import dataclasses
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

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
    """How much of the per-account upload storage is used, the per-file limit (D5), and
    today's allowance of new audio (D16)."""
    use = await uploads.usage(session, learner)
    daily = use.daily_audio
    return schemas.StorageUse(
        used_bytes=use.used_bytes,
        quota_bytes=use.quota_bytes,
        max_file_bytes=use.max_file_bytes,
        daily_audio=schemas.DailyAudio(
            used_seconds=daily.used_seconds,
            limit_seconds=daily.limit_seconds,
            clips_in_progress=daily.clips_in_progress,
            reserved_seconds=daily.reserved_seconds,
            can_add=daily.allows_more,
            resets_at=daily.resets_at,
        ),
    )


@router.post("/uploads", status_code=201)
async def start_upload(
    body: schemas.UploadRequest,
    request: Request,
    learner: CurrentLearner,
    session: DbSession,
    uploads: UploadsDep,
) -> schemas.UploadTarget:
    """Check the declared file and return a signed URL to PUT it straight to storage.

    Refused before any byte is sent: an unsupported type (`unsupported_file_type`), a
    file over the size limit (`file_too_large`), one that would take the account over
    its storage cap (`storage_full`), or any new clip once today's new audio is used up
    (429 `daily_audio_limit`, with `resets_at`). Rate-limited per learner and per IP.
    """
    started = await uploads.start(
        session,
        learner,
        body.filename,
        body.content_type,
        body.size_bytes,
        client_ip=service.client_ip(request),
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

    Creates a pending content item and queues its conversion, or keeps it in the
    learner's own queue while two of theirs are being prepared. Refused with 429
    `daily_audio_limit` once today's new audio is used up. Confirming the same upload
    again returns the same item with 200; an `Idempotency-Key` replays the first
    response exactly.
    """

    async def confirm() -> tuple[int, Any]:
        confirmed = await uploads.confirm(
            session, learner, body.upload_id, body.title, keep_video=body.keep_video
        )
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


@router.get(
    "/contents/{content_id}",
    responses={
        404: {"description": "Not in your library (`content_not_found`)"},
        410: {
            "description": (
                "Removed as a copy of a clip the learner already has (`duplicate_upload`, "
                "with `existing_content_id` and `existing_title`)"
            )
        },
    },
)
async def get_content(
    content_id: uuid.UUID, learner: CurrentLearner, session: DbSession, response: Response
) -> schemas.ContentDetail:
    """One of the learner's items: its processing status, or why it failed, and where
    to play it once it is playable."""
    detail = await service.get_content(session, learner, content_id)
    playable = detail.status == "playable"
    media_path = f"/api/v1/media/{detail.media_object_id}"
    response.headers["Cache-Control"] = "private, no-cache"
    return schemas.ContentDetail.model_validate(
        {
            **dataclasses.asdict(detail),
            "media_url": media_path if playable else None,
            "peaks_url": f"{media_path}/peaks" if playable else None,
        }
    )


_MEDIA_RESPONSES: dict[int | str, dict[str, Any]] = {
    307: {"description": "Redirect to a short-lived signed storage URL"},
    404: {"description": "No item of yours uses this media object"},
    409: {"description": "Not playable yet (`media_not_ready`)"},
}


def _redirect(url: str) -> RedirectResponse:
    # Not cached: the signed URL behind it expires within minutes.
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, no-store"})


@router.get(
    "/media/{media_object_id}",
    response_class=RedirectResponse,
    status_code=307,
    responses=_MEDIA_RESPONSES,
)
async def play_media(
    media_object_id: uuid.UUID, learner: CurrentLearner, session: DbSession, uploads: UploadsDep
) -> RedirectResponse:
    """The playback file. Redirects to a signed storage URL that serves range requests,
    so the player starts on the first bytes and seeks without downloading everything."""
    return _redirect(await service.media_url(session, uploads.storage, learner, media_object_id))


@router.get(
    "/media/{media_object_id}/peaks",
    response_class=RedirectResponse,
    status_code=307,
    responses=_MEDIA_RESPONSES,
)
async def media_peaks(
    media_object_id: uuid.UUID, learner: CurrentLearner, session: DbSession, uploads: UploadsDep
) -> RedirectResponse:
    """The waveform peaks: JSON with `per_second` values a second on a 0 to `scale` range."""
    url = await service.media_url(session, uploads.storage, learner, media_object_id, "peaks")
    return _redirect(url)
