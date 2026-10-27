"""SQL for marks (`practice.marks`, migration 58_marks).

Every statement runs in the request's transaction as the API role, so row-level
security limits it to the current learner. A new mark is one INSERT (System Design
3.2); a resend of the same id inserts nothing (ADR 0047).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class MarkRow:
    id: uuid.UUID
    session_id: uuid.UUID
    word_from: int
    word_to: int
    at_ms: int
    note: str | None
    source: str
    status: str
    tag: str | None
    created_at: datetime


_COLUMNS = "id, session_id, word_from, word_to, at_ms, note, source, status, tag, created_at"


@dataclass(frozen=True)
class NewMark:
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    word_from: int
    word_to: int
    at_ms: int
    note: str | None
    source: str
    status: str = "confirmed"
    tag: str | None = None


async def insert(session: AsyncSession, mark: NewMark) -> MarkRow | None:
    """The new mark, or None when its id or its word range is already taken."""
    row = (
        await session.execute(
            text(f"""
            INSERT INTO practice.marks
              (id, session_id, user_id, word_from, word_to, at_ms, note, source, status, tag)
            VALUES (:id, :session_id, :user_id, :word_from, :word_to, :at_ms, :note, :source,
                    :status, :tag)
            ON CONFLICT DO NOTHING
            RETURNING {_COLUMNS}
            """),
            vars(mark),
        )
    ).first()
    return MarkRow(*row) if row else None


async def get(session: AsyncSession, mark_id: uuid.UUID) -> MarkRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM practice.marks WHERE id = :id"), {"id": mark_id}
        )
    ).first()
    return MarkRow(*row) if row else None


async def find_range(
    session: AsyncSession, session_id: uuid.UUID, word_from: int, word_to: int
) -> MarkRow | None:
    row = (
        await session.execute(
            text(f"""
            SELECT {_COLUMNS} FROM practice.marks
             WHERE session_id = :session_id AND word_from = :word_from AND word_to = :word_to
            """),
            {"session_id": session_id, "word_from": word_from, "word_to": word_to},
        )
    ).first()
    return MarkRow(*row) if row else None


async def list_for_session(session: AsyncSession, session_id: uuid.UUID) -> list[MarkRow]:
    """The session's marks in audio order (index `marks_session_idx`)."""
    rows = await session.execute(
        text(f"""
        SELECT {_COLUMNS} FROM practice.marks
         WHERE session_id = :session_id
         ORDER BY at_ms, word_from, word_to
        """),
        {"session_id": session_id},
    )
    return [MarkRow(*row) for row in rows]


async def set_note(
    session: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID, note: str | None
) -> MarkRow | None:
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.marks SET note = :note
             WHERE id = :id AND session_id = :session_id
            RETURNING {_COLUMNS}
            """),
            {"id": mark_id, "session_id": session_id, "note": note},
        )
    ).first()
    return MarkRow(*row) if row else None


async def set_tag(
    session: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID, tag: str | None
) -> MarkRow | None:
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.marks SET tag = :tag
             WHERE id = :id AND session_id = :session_id
            RETURNING {_COLUMNS}
            """),
            {"id": mark_id, "session_id": session_id, "tag": tag},
        )
    ).first()
    return MarkRow(*row) if row else None


async def confirm(
    session: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID
) -> MarkRow | None:
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.marks SET status = 'confirmed'
             WHERE id = :id AND session_id = :session_id
            RETURNING {_COLUMNS}
            """),
            {"id": mark_id, "session_id": session_id},
        )
    ).first()
    return MarkRow(*row) if row else None


async def delete(session: AsyncSession, session_id: uuid.UUID, mark_id: uuid.UUID) -> bool:
    deleted = await session.execute(
        text("DELETE FROM practice.marks WHERE id = :id AND session_id = :session_id RETURNING id"),
        {"id": mark_id, "session_id": session_id},
    )
    return deleted.first() is not None
