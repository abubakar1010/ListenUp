"""SQL for the content module. Every statement runs under the learner's row-level security."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class UploadRow:
    id: uuid.UUID
    storage_key: str
    filename: str
    content_type: str
    size_bytes: int
    content_id: uuid.UUID | None
    created_at: datetime


@dataclass(frozen=True)
class ContentRow:
    id: uuid.UUID
    title: str
    source: str
    status: str
    duration_ms: int | None
    created_at: datetime


async def lock_learner_uploads(session: AsyncSession, learner: uuid.UUID) -> None:
    """Serialise this learner's upload requests until the transaction ends.

    Two requests at once would otherwise both pass the storage cap check.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('content.uploads:' || :id, 0))"),
        {"id": str(learner)},
    )


async def stored_upload_bytes(
    session: AsyncSession, learner: uuid.UUID, confirm_window: timedelta
) -> int:
    """Bytes of the learner's uploads in their library, plus uploads they may still confirm."""
    used = await session.scalar(
        text("""
        SELECT coalesce(sum(size_bytes), 0) FROM content.uploads
         WHERE user_id = :id
           AND (confirmed_at IS NOT NULL OR created_at > now() - :window)
        """),
        {"id": learner, "window": confirm_window},
    )
    return int(used or 0)


async def insert_upload(
    session: AsyncSession,
    *,
    upload_id: uuid.UUID,
    learner: uuid.UUID,
    storage_key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> None:
    await session.execute(
        text("""
        INSERT INTO content.uploads (id, user_id, storage_key, filename, content_type, size_bytes)
        VALUES (:id, :user_id, :key, :filename, :content_type, :size)
        """),
        {
            "id": upload_id,
            "user_id": learner,
            "key": storage_key,
            "filename": filename,
            "content_type": content_type,
            "size": size_bytes,
        },
    )


async def lock_upload(session: AsyncSession, upload_id: uuid.UUID) -> UploadRow | None:
    """The learner's upload, locked so two confirmations of it run one after the other."""
    row = (
        await session.execute(
            text("""
            SELECT id, storage_key, filename, content_type, size_bytes, content_id, created_at
              FROM content.uploads WHERE id = :id FOR UPDATE
            """),
            {"id": upload_id},
        )
    ).first()
    return UploadRow(*row) if row else None


async def delete_upload(session: AsyncSession, upload_id: uuid.UUID) -> None:
    await session.execute(text("DELETE FROM content.uploads WHERE id = :id"), {"id": upload_id})


async def insert_upload_media(
    session: AsyncSession, *, media_id: uuid.UUID, learner: uuid.UUID, fingerprint: str
) -> None:
    await session.execute(
        text("""
        INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by)
        VALUES (:id, :fingerprint, 'upload', :learner)
        """),
        {"id": media_id, "fingerprint": fingerprint, "learner": learner},
    )


async def insert_content(
    session: AsyncSession,
    *,
    content_id: uuid.UUID,
    learner: uuid.UUID,
    media_id: uuid.UUID,
    title: str,
    keep_video: bool = False,
) -> None:
    await session.execute(
        text("""
        INSERT INTO content.contents (id, user_id, media_object_id, title, keep_video)
        VALUES (:id, :learner, :media_id, :title, :keep_video)
        """),
        {
            "id": content_id,
            "learner": learner,
            "media_id": media_id,
            "title": title,
            "keep_video": keep_video,
        },
    )


async def mark_upload_confirmed(
    session: AsyncSession, upload_id: uuid.UUID, content_id: uuid.UUID, media_id: uuid.UUID
) -> None:
    await session.execute(
        text("""
        UPDATE content.uploads
           SET content_id = :content_id, media_object_id = :media_id, confirmed_at = now()
         WHERE id = :id
        """),
        {"id": upload_id, "content_id": content_id, "media_id": media_id},
    )


_CONTENT_COLUMNS = """
SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at
  FROM content.contents c
  JOIN content.media_objects m ON m.id = c.media_object_id
"""


async def get_content(session: AsyncSession, content_id: uuid.UUID) -> ContentRow | None:
    row = (
        await session.execute(text(_CONTENT_COLUMNS + " WHERE c.id = :id"), {"id": content_id})
    ).first()
    return ContentRow(*row) if row else None


async def list_contents(
    session: AsyncSession,
    learner: uuid.UUID,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[ContentRow]:
    """The learner's items, newest first, starting after `after` (keyset on
    contents_library_idx)."""
    params: dict[str, object] = {"learner": learner, "limit": limit}
    where = "WHERE c.user_id = :learner"
    if after is not None:
        where += " AND (c.created_at, c.id) < (:after_at, :after_id)"
        params.update(after_at=after[0], after_id=after[1])
    rows = await session.execute(
        text(f"{_CONTENT_COLUMNS} {where} ORDER BY c.created_at DESC, c.id DESC LIMIT :limit"),
        params,
    )
    return [ContentRow(*row) for row in rows]


# -- Conversion (#36). The worker connects with BYPASSRLS, so these see every row. --


@dataclass(frozen=True)
class ConversionState:
    media_id: uuid.UUID
    learner: uuid.UUID
    status: str
    fingerprint: str
    source_key: str
    content_id: uuid.UUID
    keep_video: bool


async def conversion_state(
    session: AsyncSession, media_id: uuid.UUID, upload_id: uuid.UUID
) -> ConversionState | None:
    """The upload's media object, locked; None once the item or its media is gone."""
    row = (
        await session.execute(
            text("""
            SELECT m.id, u.user_id, m.status, m.fingerprint, u.storage_key, c.id, c.keep_video
              FROM content.uploads u
              JOIN content.media_objects m ON m.id = u.media_object_id
              JOIN content.contents c ON c.id = u.content_id
             WHERE u.id = :upload_id AND m.id = :media_id
               FOR UPDATE OF m
            """),
            {"upload_id": upload_id, "media_id": media_id},
        )
    ).first()
    return ConversionState(*row) if row else None


@dataclass(frozen=True)
class FingerprintOwner:
    media_id: uuid.UUID
    status: str
    learner_content_id: uuid.UUID | None  # the learner's item on it, if any
    other_references: int  # content items of anyone else (always 0 for uploads)


async def fingerprint_owner(
    session: AsyncSession, fingerprint: str, learner: uuid.UUID
) -> FingerprintOwner | None:
    row = (
        await session.execute(
            text("""
            SELECT m.id, m.status,
                   (SELECT c.id FROM content.contents c
                     WHERE c.media_object_id = m.id AND c.user_id = :learner),
                   (SELECT count(*) FROM content.contents c
                     WHERE c.media_object_id = m.id AND c.user_id <> :learner)
              FROM content.media_objects m
             WHERE m.fingerprint = :fingerprint
               FOR UPDATE OF m
            """),
            {"fingerprint": fingerprint, "learner": learner},
        )
    ).first()
    return FingerprintOwner(row[0], row[1], row[2], int(row[3])) if row else None


async def set_fingerprint(session: AsyncSession, media_id: uuid.UUID, fingerprint: str) -> None:
    await session.execute(
        text("UPDATE content.media_objects SET fingerprint = :fp WHERE id = :id"),
        {"id": media_id, "fp": fingerprint},
    )


async def delete_content_item(session: AsyncSession, content_id: uuid.UUID) -> None:
    """Its upload row and sessions go with it (ON DELETE CASCADE); the trigger counts down."""
    await session.execute(text("DELETE FROM content.contents WHERE id = :id"), {"id": content_id})


async def delete_media(session: AsyncSession, media_id: uuid.UUID) -> None:
    await session.execute(
        text("DELETE FROM content.media_objects WHERE id = :id"), {"id": media_id}
    )


async def mark_media_failed(session: AsyncSession, media_id: uuid.UUID, error_code: str) -> bool:
    """Fail a media object that is still being prepared; False when it was not."""
    result = await session.execute(
        text("""
        UPDATE content.media_objects SET status = 'failed', error_code = :code
         WHERE id = :id AND status IN ('pending', 'downloading')
        RETURNING id
        """),
        {"id": media_id, "code": error_code},
    )
    return result.first() is not None


async def mark_media_playable(
    session: AsyncSession,
    media_id: uuid.UUID,
    *,
    duration_ms: int,
    has_video: bool,
    playback_key: str,
    peaks_key: str,
    playback_bytes: int,
) -> bool:
    """Record the playback file; False when the media object is gone or already failed."""
    result = await session.execute(
        text("""
        UPDATE content.media_objects
           SET status = 'playable', error_code = NULL, duration_ms = :duration_ms,
               has_video = :has_video, playback_key = :playback_key, peaks_key = :peaks_key,
               playback_bytes = :playback_bytes
         WHERE id = :id AND status IN ('pending', 'downloading', 'playable')
        RETURNING id
        """),
        {
            "id": media_id,
            "duration_ms": duration_ms,
            "has_video": has_video,
            "playback_key": playback_key,
            "peaks_key": peaks_key,
            "playback_bytes": playback_bytes,
        },
    )
    return result.first() is not None


async def media_content_owners(
    session: AsyncSession, media_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(learner, content id) of every item on this media object, to tell each learner."""
    rows = await session.execute(
        text("SELECT user_id, id FROM content.contents WHERE media_object_id = :id"),
        {"id": media_id},
    )
    return [(row[0], row[1]) for row in rows]


# -- Reading a learner's item and its media. These run under row-level security. --


@dataclass(frozen=True)
class ContentDetailRow:
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


async def get_content_detail(
    session: AsyncSession, learner: uuid.UUID, content_id: uuid.UUID
) -> ContentDetailRow | None:
    row = (
        await session.execute(
            text("""
            SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at,
                   m.id, m.has_video, c.keep_video, m.error_code
              FROM content.contents c
              JOIN content.media_objects m ON m.id = c.media_object_id
             WHERE c.id = :id AND c.user_id = :learner
            """),
            {"id": content_id, "learner": learner},
        )
    ).first()
    return ContentDetailRow(*row) if row else None


@dataclass(frozen=True)
class MediaFiles:
    status: str
    playback_key: str | None
    peaks_key: str | None


async def learner_media(
    session: AsyncSession, learner: uuid.UUID, media_id: uuid.UUID
) -> MediaFiles | None:
    """The media object's files, only when the learner has a content item on it."""
    row = (
        await session.execute(
            text("""
            SELECT m.status, m.playback_key, m.peaks_key
              FROM content.contents c
              JOIN content.media_objects m ON m.id = c.media_object_id
             WHERE c.media_object_id = :media_id AND c.user_id = :learner
            """),
            {"media_id": media_id, "learner": learner},
        )
    ).first()
    return MediaFiles(*row) if row else None
