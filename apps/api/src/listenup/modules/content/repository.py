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
) -> None:
    await session.execute(
        text("""
        INSERT INTO content.contents (id, user_id, media_object_id, title)
        VALUES (:id, :learner, :media_id, :title)
        """),
        {"id": content_id, "learner": learner, "media_id": media_id, "title": title},
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
