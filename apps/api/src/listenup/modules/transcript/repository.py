"""Shared cache persistence and RLS-scoped learner correction reads."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.transcript.domain.spans import Span
from listenup.modules.transcript.models import PassageTranscript, TranscriptCorrection
from listenup.modules.transcript.packing import Packed
from listenup.platform.database import Database
from listenup.platform.ids import uuid7
from listenup.platform.jobs import Reschedule


async def overlapping(db: AsyncSession, media_id: uuid.UUID, span: Span) -> list[PassageTranscript]:
    rows = await db.scalars(
        select(PassageTranscript)
        .where(
            PassageTranscript.media_object_id == media_id,
            PassageTranscript.span.overlaps(Range(*span)),
            PassageTranscript.status == "ready",
        )
        .order_by(PassageTranscript.span)
    )
    return list(rows)


async def corrections(
    db: AsyncSession, learner: uuid.UUID, transcript_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, int], str]:
    rows = await db.scalars(
        select(TranscriptCorrection).where(
            TranscriptCorrection.user_id == learner,
            TranscriptCorrection.passage_transcript_id.in_(transcript_ids),
        )
    )
    return {(row.passage_transcript_id, row.word_index): row.corrected_text for row in rows}


async def store(db: AsyncSession, media_id: uuid.UUID, span: Span, packed: Packed) -> None:
    db.add(
        PassageTranscript(
            id=uuid7(),
            media_object_id=media_id,
            span=Range(*span),
            origin="generated",
            status="ready",
            words=packed.words,
            start_ms=packed.start_ms,
            end_ms=packed.end_ms,
            confidence=packed.confidence,
            sentence_starts=packed.sentence_starts,
            provider_info=packed.provider_info,
        )
    )
    await db.flush()


async def failed(db: AsyncSession, media_id: uuid.UUID, span: Span) -> bool:
    return (
        await db.scalar(
            select(PassageTranscript.id)
            .where(
                PassageTranscript.media_object_id == media_id,
                PassageTranscript.span.overlaps(Range(*span)),
                PassageTranscript.status == "failed",
            )
            .limit(1)
        )
    ) is not None


async def mark_failed(db: AsyncSession, media_id: uuid.UUID, spans: list[Span]) -> None:
    from sqlalchemy import delete

    # Replace previous failure markers; they never count as cached coverage.
    await db.execute(
        delete(PassageTranscript).where(
            PassageTranscript.media_object_id == media_id,
            PassageTranscript.status == "failed",
            PassageTranscript.span.in_([Range(*span) for span in spans]),
        )
    )
    for span in spans:
        db.add(
            PassageTranscript(
                id=uuid7(),
                media_object_id=media_id,
                span=Range(*span),
                origin="generated",
                status="failed",
            )
        )


@asynccontextmanager
async def media_lock(database: Database, media_id: uuid.UUID) -> AsyncIterator[None]:
    """Session lock across short transactions, never an idle transaction during AI.

    Queue resource locks serialize normal jobs. This lock also covers direct retries
    and failure settlement. Invalidate the connection on cleanup failure so a pooled
    connection can never retain a session-level lock.
    """
    async with database.engine.connect() as connection:
        key = {"key": f"transcript:{media_id}"}
        acquired = False
        try:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), key
                )
            )
            await connection.commit()
            if not acquired:
                raise Reschedule(datetime.now(UTC) + timedelta(seconds=2))
            yield
        finally:
            if acquired:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key
                    )
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise
