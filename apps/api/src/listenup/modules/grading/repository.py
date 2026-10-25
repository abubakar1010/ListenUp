"""Worker-only shared cache; no API-role grant or learner-specific reference."""

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.grading.models import GistGrade, KeyPoints
from listenup.platform.ids import uuid7


async def find(
    db: AsyncSession, media_id: uuid.UUID, span: tuple[int, int], version: str
) -> KeyPoints | None:
    return await db.scalar(
        select(KeyPoints).where(
            KeyPoints.media_object_id == media_id,
            KeyPoints.span == Range(*span),
            KeyPoints.prompt_version == version,
        )
    )


async def store(
    db: AsyncSession,
    media_id: uuid.UUID,
    span: tuple[int, int],
    version: str,
    points: list[dict[str, str]],
    provenance: dict[str, Any],
) -> None:
    await db.execute(
        insert(KeyPoints)
        .values(
            id=uuid7(),
            media_object_id=media_id,
            span=Range(*span),
            prompt_version=version,
            points=points,
            provider_info=provenance,
        )
        .on_conflict_do_nothing(index_elements=["media_object_id", "span", "prompt_version"])
    )


async def ensure_pending(db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID) -> None:
    await db.execute(
        insert(GistGrade)
        .values(attempt_id=attempt, user_id=learner)
        .on_conflict_do_nothing(index_elements=["attempt_id"])
    )


async def grade(db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID) -> GistGrade | None:
    return await db.scalar(
        select(GistGrade).where(GistGrade.attempt_id == attempt, GistGrade.user_id == learner)
    )


async def finish_grade(
    db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID, values: dict[str, Any]
) -> bool:
    result = await db.scalar(
        update(GistGrade)
        .where(
            GistGrade.attempt_id == attempt,
            GistGrade.user_id == learner,
            GistGrade.status == "pending",
        )
        .values(
            **values,
            status="ready",
            updated_at=func.now(),
            attempts_made=GistGrade.attempts_made + 1,
        )
        .returning(GistGrade.attempt_id)
    )
    return result is not None


async def points_by_id(db: AsyncSession, key: uuid.UUID) -> list[dict[str, str]] | None:
    return await db.scalar(select(KeyPoints.points).where(KeyPoints.id == key))
