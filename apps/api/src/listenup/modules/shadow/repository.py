"""Learner-scoped segment persistence; serialize proposals and edits per session."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.shadow.models import ShadowRound, ShadowSegment
from listenup.platform.ids import uuid7


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


async def rounds(db: AsyncSession, session_id: uuid.UUID) -> list[ShadowRound]:
    return list(
        await db.scalars(
            select(ShadowRound)
            .where(ShadowRound.session_id == session_id)
            .order_by(ShadowRound.round)
        )
    )


async def insert_round(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, number: int
) -> None:
    db.add(ShadowRound(id=uuid7(), session_id=session_id, user_id=user_id, round=number))
    await db.flush()


async def round_by_id(
    db: AsyncSession, round_id: uuid.UUID, *, lock: bool = False
) -> ShadowRound | None:
    query = select(ShadowRound).where(ShadowRound.id == round_id)
    return await db.scalar(query.with_for_update() if lock else query)
