"""Worker-only shared cache; no API-role grant or learner-specific reference."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.grading.models import GistGrade, KeyPointDelay, KeyPoints, RoundGrade
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


async def ensure_pending(
    db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID, deadline: datetime
) -> None:
    await db.execute(
        insert(GistGrade)
        .values(attempt_id=attempt, user_id=learner, feedback_deadline=deadline)
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
            GistGrade.status != "ready",
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


async def expire_feedback(
    db: AsyncSession,
    learner: uuid.UUID,
    attempt: uuid.UUID,
    now: datetime,
    *,
    deadline: datetime | None = None,
) -> None:
    statement = update(GistGrade).where(
        GistGrade.attempt_id == attempt,
        GistGrade.user_id == learner,
        GistGrade.status == "pending",
        GistGrade.feedback_deadline <= now,
    )
    if deadline is not None:
        statement = statement.where(GistGrade.feedback_deadline == deadline)
    await db.execute(statement.values(status="unavailable", updated_at=func.now()))


async def feedback_state(
    db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID, state: str
) -> None:
    await db.execute(
        update(GistGrade)
        .where(
            GistGrade.attempt_id == attempt,
            GistGrade.user_id == learner,
            GistGrade.status != "ready",
        )
        .values(status=state, updated_at=func.now())
    )


async def reference_delayed(
    db: AsyncSession, media: uuid.UUID, span: tuple[int, int], version: str
) -> bool:
    return (
        await db.scalar(
            select(KeyPointDelay.media_object_id).where(
                KeyPointDelay.media_object_id == media,
                KeyPointDelay.span == Range(*span),
                KeyPointDelay.prompt_version == version,
            )
        )
        is not None
    )


async def clear_feedback_delay(db: AsyncSession, learner: uuid.UUID, attempt: uuid.UUID) -> None:
    await db.execute(
        update(GistGrade)
        .where(
            GistGrade.attempt_id == attempt,
            GistGrade.user_id == learner,
            GistGrade.status == "delayed",
        )
        .values(status="pending", updated_at=func.now())
    )


async def set_reference_delay(
    db: AsyncSession, media: uuid.UUID, span: tuple[int, int], version: str, delayed: bool
) -> None:
    if delayed:
        await db.execute(
            insert(KeyPointDelay)
            .values(media_object_id=media, span=Range(*span), prompt_version=version)
            .on_conflict_do_nothing()
        )
    else:
        await db.execute(
            delete(KeyPointDelay).where(
                KeyPointDelay.media_object_id == media,
                KeyPointDelay.span == Range(*span),
                KeyPointDelay.prompt_version == version,
            )
        )


async def round_grade(
    db: AsyncSession, learner: uuid.UUID, round_id: uuid.UUID, *, lock: bool = False
) -> RoundGrade | None:
    from listenup.modules.grading.models import RoundGrade

    query = select(RoundGrade).where(RoundGrade.round_id == round_id, RoundGrade.user_id == learner)
    return await db.scalar(query.with_for_update() if lock else query)


async def expire_round(
    db: AsyncSession,
    learner: uuid.UUID,
    round_id: uuid.UUID,
    now: datetime,
    generation: uuid.UUID | None = None,
) -> None:
    from listenup.modules.grading.models import RoundGrade

    query = update(RoundGrade).where(
        RoundGrade.round_id == round_id,
        RoundGrade.user_id == learner,
        RoundGrade.status == "pending",
        RoundGrade.feedback_deadline <= now,
    )
    if generation is not None:
        query = query.where(RoundGrade.generation == generation)
    await db.execute(query.values(status="unavailable", updated_at=func.now()))


async def round_unavailable(
    db: AsyncSession, learner: uuid.UUID, round_id: uuid.UUID, generation: uuid.UUID
) -> None:
    from listenup.modules.grading.models import RoundGrade

    await db.execute(
        update(RoundGrade)
        .where(
            RoundGrade.round_id == round_id,
            RoundGrade.user_id == learner,
            RoundGrade.generation == generation,
            RoundGrade.measures.is_(None),
        )
        .values(status="unavailable", updated_at=func.now())
    )


async def finish_round(
    db: AsyncSession,
    learner: uuid.UUID,
    round_id: uuid.UUID,
    generation: uuid.UUID,
    values: dict[str, Any],
) -> bool:
    from listenup.modules.grading.models import RoundGrade

    result = await db.scalar(
        update(RoundGrade)
        .where(
            RoundGrade.round_id == round_id,
            RoundGrade.user_id == learner,
            RoundGrade.generation == generation,
            RoundGrade.measures.is_(None),
        )
        .values(
            **values,
            status="scored" if values["overall"] is not None else "unavailable",
            updated_at=func.now(),
        )
        .returning(RoundGrade.round_id)
    )
    return result is not None
