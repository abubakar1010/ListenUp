"""Learner-scoped segment persistence; serialize proposals and edits per session."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.shadow.models import ShadowSegment


async def get(db: AsyncSession, session_id: uuid.UUID) -> ShadowSegment | None:
    return await db.scalar(
        select(ShadowSegment).where(ShadowSegment.session_id == session_id).with_for_update()
    )


async def save(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    start: int,
    end: int,
    count: int,
    chosen_by: Literal["system", "learner"],
) -> ShadowSegment:
    row = await get(db, session_id)
    if row is None:
        row = ShadowSegment(session_id=session_id, user_id=user_id)
        db.add(row)
    row.span = Range(start, end)
    row.mark_count = count
    row.chosen_by = chosen_by
    await db.flush()
    return row
