"""Content intake and the learner's content items (FR-CI-1, FR-CI-3, FR-CI-6, FR-LB-1).

The public face of the content module. Uploads go straight from the browser to
storage (Architecture 5.1, 9.2; ADR 0020):

1. `Uploads.start` checks the declared file and the learner's storage cap, records a
   pending row in `content.uploads` and returns a signed PUT URL bound to the file's
   type and exact size, under `users/<user id>/uploads/`.
2. The browser PUTs the file to storage, with progress and cancel.
3. `Uploads.confirm` checks that the object is in storage with the declared size, then
   creates the pending media object, the learner's content item and the conversion job
   in one transaction.

4. The conversion job (`jobs.convert_upload`, #36) checks the real streams, writes the
   playback file and the waveform peaks, and makes the media object `playable`.

Other modules (the library) read content items through `list_contents`. The learner
plays a clip through `media_url`, which checks that they have an item on that media
object and hands out a short-lived signed URL (Architecture 9.2: Media).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import jobs, repository
from listenup.modules.content.domain import cursor as cursors
from listenup.modules.content.domain.files import (
    check_file,
    default_title,
    extension,
    format_size,
    normalized_type,
)
from listenup.modules.content.domain.media import failure_message
from listenup.platform.config import Settings
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7
from listenup.platform.rate_limit import Limit, RateLimiter, user_key
from listenup.platform.storage import Storage

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class StartedUpload:
    upload_id: uuid.UUID
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class StorageUse:
    used_bytes: int
    quota_bytes: int
    max_file_bytes: int


@dataclass(frozen=True)
class ContentSummary:
    """One item of a learner's library."""

    id: uuid.UUID
    title: str
    source: str  # 'upload' or 'youtube'
    status: str  # the media object's: pending, downloading, playable, failed, expired
    duration_ms: int | None
    created_at: datetime


@dataclass(frozen=True)
class ContentDetail:
    """One item with what its page needs to show and play it."""

    id: uuid.UUID
    title: str
    source: str
    status: str
    duration_ms: int | None
    created_at: datetime
    media_object_id: uuid.UUID
    has_video: bool
    keep_video: bool
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True)
class ContentPage:
    items: list[ContentSummary]
    next_cursor: str | None


@dataclass(frozen=True)
class Confirmed:
    item: ContentSummary
    created: bool  # False when the upload had been confirmed before


def upload_key(learner: uuid.UUID, upload_id: uuid.UUID, filename: str) -> str:
    """Under the learner's prefix, so deleting the account removes it (Architecture 8.1)."""
    return f"users/{learner}/uploads/{upload_id}.{extension(filename)}"


def provisional_fingerprint(learner: uuid.UUID, upload_id: uuid.UUID) -> str:
    """Unique until the conversion job hashes the file and sets `upload:<user>:<sha256>`."""
    return f"upload:{learner}:pending:{upload_id}"


class Uploads:
    def __init__(self, settings: Settings, storage: Storage, limiter: RateLimiter) -> None:
        self.settings = settings
        self.storage = storage
        self.limiter = limiter
        self.per_learner = Limit("upload", settings.upload_rate_limit, timedelta(hours=1))
        self.confirm_window = timedelta(hours=settings.upload_confirm_hours)

    async def usage(self, session: AsyncSession, learner: uuid.UUID) -> StorageUse:
        used = await repository.stored_upload_bytes(session, learner, self.confirm_window)
        return StorageUse(used, self.settings.upload_quota_bytes, self.settings.upload_max_bytes)

    async def start(
        self,
        session: AsyncSession,
        learner: uuid.UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> StartedUpload:
        """Refuse a file that cannot be used before any byte is sent (FR-CI-3, D5)."""
        await self.limiter.enforce(self.per_learner, user_key(self.per_learner, learner))
        if problem := check_file(
            filename, content_type, size_bytes, self.settings.upload_max_bytes
        ):
            raise ProblemError(422, problem.code, problem.detail)

        await repository.lock_learner_uploads(session, learner)
        used = await repository.stored_upload_bytes(session, learner, self.confirm_window)
        quota = self.settings.upload_quota_bytes
        if used + size_bytes > quota:
            raise ProblemError(
                422,
                "storage_full",
                f"You have used {format_size(used)} of {format_size(quota)}, and this file is "
                f"{format_size(size_bytes)}. Delete a clip you have finished to make room.",
                used_bytes=used,
                quota_bytes=quota,
            )

        upload_id = uuid7()
        key = upload_key(learner, upload_id, filename)
        mime = normalized_type(content_type)
        await repository.insert_upload(
            session,
            upload_id=upload_id,
            learner=learner,
            storage_key=key,
            filename=filename,
            content_type=mime,
            size_bytes=size_bytes,
        )
        signed = self.storage.signed_upload(key, mime, content_length=size_bytes)
        return StartedUpload(
            upload_id,
            signed.url,
            signed.method,
            signed.headers,
            datetime.fromtimestamp(signed.expires_at, UTC),
        )

    async def cancel(self, session: AsyncSession, upload_id: uuid.UUID) -> None:
        """Forget an upload the learner cancelled; its storage object, if any, goes too."""
        upload = await repository.lock_upload(session, upload_id)
        if upload is None:
            raise _upload_not_found()
        if upload.content_id is not None:
            raise ProblemError(
                409,
                "upload_confirmed",
                "This upload is already in your library. Delete the clip there instead.",
            )
        await repository.delete_upload(session, upload_id)
        await self.storage.delete(upload.storage_key)

    async def confirm(
        self,
        session: AsyncSession,
        learner: uuid.UUID,
        upload_id: uuid.UUID,
        title: str | None,
        *,
        keep_video: bool = False,
    ) -> Confirmed:
        """Turn an upload that reached storage into a pending content item (FR-CI-1)."""
        upload = await repository.lock_upload(session, upload_id)
        if upload is None:
            raise _upload_not_found()
        if upload.content_id is not None:
            existing = await repository.get_content(session, upload.content_id)
            if existing is not None:
                return Confirmed(_summary(existing), created=False)
            raise _upload_not_found()
        if upload.created_at < datetime.now(UTC) - self.confirm_window:
            raise ProblemError(
                409, "upload_expired", "This upload is too old to add. Upload the file again."
            )

        stored = await self.storage.head(upload.storage_key)
        if stored is None:
            raise ProblemError(
                409,
                "upload_incomplete",
                "We have not received the file yet. Wait for the upload to finish, "
                "or upload the file again.",
            )
        if stored.size != upload.size_bytes:
            # Signed uploads are bound to the size, so this is not a slow connection.
            await self.storage.delete(upload.storage_key)
            raise ProblemError(
                409,
                "upload_size_mismatch",
                f"The file we received is {format_size(stored.size)}, not the "
                f"{format_size(upload.size_bytes)} you chose. Upload the file again.",
            )

        media_id = uuid7()
        content_id = uuid7()
        await repository.insert_upload_media(
            session,
            media_id=media_id,
            learner=learner,
            fingerprint=provisional_fingerprint(learner, upload_id),
        )
        await repository.insert_content(
            session,
            content_id=content_id,
            learner=learner,
            media_id=media_id,
            title=_title(title, upload.filename),
            keep_video=keep_video,
        )
        await repository.mark_upload_confirmed(session, upload_id, content_id, media_id)
        await jobs.queue_conversion(session, media_id, upload_id)
        created = await repository.get_content(session, content_id)
        assert created is not None
        return Confirmed(_summary(created), created=True)


def _title(title: str | None, filename: str) -> str:
    if title is not None:
        cleaned = " ".join(title.split())[:300]
        if cleaned:
            return cleaned
    return default_title(filename)


def _upload_not_found() -> ProblemError:
    return ProblemError(
        404, "upload_not_found", "We could not find this upload. Choose the file again."
    )


def _summary(row: repository.ContentRow) -> ContentSummary:
    return ContentSummary(
        row.id, row.title, row.source, row.status, row.duration_ms, row.created_at
    )


async def list_contents(
    session: AsyncSession,
    learner: uuid.UUID,
    cursor: str | None = None,
    limit: int = PAGE_SIZE,
) -> ContentPage:
    """The learner's content items, newest first, one keyset page at a time (FR-LB-1)."""
    after = None
    if cursor:
        try:
            decoded = cursors.decode(cursor)
        except cursors.InvalidCursor as error:
            raise ProblemError(
                400, "invalid_cursor", "This page link is not valid. Load the list again."
            ) from error
        after = (decoded.created_at, decoded.id)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    rows = await repository.list_contents(session, learner, limit + 1, after)
    items = [_summary(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = cursors.encode(cursors.Cursor(last.created_at, last.id))
    return ContentPage(items, next_cursor)


async def get_content(
    session: AsyncSession, learner: uuid.UUID, content_id: uuid.UUID
) -> ContentDetail:
    """The learner's item; 404 for anyone else's or one that is gone."""
    row = await repository.get_content_detail(session, learner, content_id)
    if row is None:
        raise ProblemError(
            404, "content_not_found", "This clip is not in your library. Go back to the library."
        )
    return ContentDetail(
        row.id,
        row.title,
        row.source,
        row.status,
        row.duration_ms,
        row.created_at,
        row.media_object_id,
        row.has_video,
        row.keep_video,
        row.error_code if row.status == "failed" else None,
        failure_message(row.error_code) if row.status == "failed" else None,
    )


MediaFile = Literal["playback", "peaks"]


async def media_url(
    session: AsyncSession,
    storage: Storage,
    learner: uuid.UUID,
    media_id: uuid.UUID,
    file: MediaFile = "playback",
) -> str:
    """A short-lived signed URL for a media object's file (NFR-SEC-2, FR-CI-6).

    Only a learner with a content item on the media object gets one; anyone else gets
    404, the same as for a media object that does not exist. Signed URLs are reused
    while fresh, so the browser cache keeps working; range requests then go straight
    to storage (System Design 6.4).
    """
    files = await repository.learner_media(session, learner, media_id)
    if files is None:
        raise ProblemError(404, "media_not_found", "This clip is not in your library.")
    key = files.playback_key if file == "playback" else files.peaks_key
    if files.status != "playable" or key is None:
        raise ProblemError(
            409,
            "media_not_ready",
            "This clip is not ready to play yet. Wait until it shows as ready.",
            media_status=files.status,
        )
    return storage.signed_download(key).url


def get_uploads(request: Request) -> Uploads:
    uploads: Uploads = request.app.state.uploads
    return uploads


def build_uploads(settings: Settings, storage: Storage, limiter: RateLimiter) -> Uploads:
    return Uploads(settings, storage, limiter)


UploadsDep = Annotated[Uploads, Depends(get_uploads)]
