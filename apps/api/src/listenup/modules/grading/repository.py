"""Worker-only shared cache; no API-role grant or learner-specific reference."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.grading.models import KeyPoints
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
