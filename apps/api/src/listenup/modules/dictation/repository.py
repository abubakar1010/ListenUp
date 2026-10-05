"""SQL for Dictation drafts (`practice.dictation_attempts`, migration 0010).

Every statement runs in the request's transaction as the API role, so row-level
security limits it to the current learner. Nothing here reads a transcript: the
reference text belongs to the transcript module and Dictation never shows it
(FR-DI-3, FR-TX-5).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DraftRow:
    attempt_id: uuid.UUID
    draft_text: str
    draft_version: int
    updated_at: datetime


_COLUMNS = "attempt_id, draft_text, draft_version, updated_at"


async def ensure_draft(
    session: AsyncSession, attempt_id: uuid.UUID, user_id: uuid.UUID
) -> DraftRow:
    """The attempt's draft row, created empty if it has none yet (safe to repeat)."""
    await session.execute(
        text("""
        INSERT INTO practice.dictation_attempts (attempt_id, user_id)
        VALUES (:attempt_id, :user_id)
        ON CONFLICT (attempt_id) DO NOTHING
        """),
        {"attempt_id": attempt_id, "user_id": user_id},
    )
    found = await get_draft(session, attempt_id)
    assert found is not None  # just inserted or already there, and the learner's own
    return found


async def get_draft(session: AsyncSession, attempt_id: uuid.UUID) -> DraftRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM practice.dictation_attempts WHERE attempt_id = :id"),
            {"id": attempt_id},
        )
    ).first()
    return DraftRow(*row) if row else None


async def save_draft(
    session: AsyncSession, attempt_id: uuid.UUID, draft_text: str, base_version: int
) -> DraftRow | None:
    """Write the draft if it is still at `base_version`, bumping the version; else None."""
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.dictation_attempts
               SET draft_text = :draft_text, draft_version = draft_version + 1
             WHERE attempt_id = :id AND draft_version = :base_version
            RETURNING {_COLUMNS}
            """),
            {"id": attempt_id, "draft_text": draft_text, "base_version": base_version},
        )
    ).first()
    return DraftRow(*row) if row else None
