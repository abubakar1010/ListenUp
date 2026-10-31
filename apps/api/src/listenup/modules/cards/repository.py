"""Cards SQL, always under learner RLS in the request transaction."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.cards import schemas
from listenup.modules.cards.domain.cursor import Cursor
from listenup.platform.jobs import Reschedule

_COLUMNS = (
    "c.id, c.session_id, c.slot, c.mark_id, c.written_form, c.heard_form, "
    "c.at_ms, c.created_at, c.audio_status, s.content_id"
)


async def require_no_audio_writes(db: AsyncSession, learner: uuid.UUID) -> None:
    """Called under purge's exclusive account lock, before any storage sweep."""
    if await db.scalar(
        text("SELECT EXISTS (SELECT 1 FROM practice.card_snippet_writes WHERE user_id=:user)"),
        {"user": learner},
    ):
        raise Reschedule(datetime.now(UTC) + timedelta(minutes=1))


async def lock_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    # Serialize creates and completion. Recheck the step after acquiring this lock.
    await db.execute(
        text("SELECT id FROM practice.sessions WHERE id=:id FOR UPDATE"), {"id": session_id}
    )


async def insert(db: AsyncSession, values: dict[str, object]) -> uuid.UUID | None:
    row = (
        await db.execute(
            text("""
        INSERT INTO practice.cards (id, session_id, user_id, slot, mark_id, media_object_id,
                                   at_ms, written_form, heard_form, snippet_span, audio_status,
                                   audio_generation)
        SELECT :id, :session_id, :user_id, slot, :mark_id, :media_object_id, :at_ms,
               :written_form, :heard_form, int4range(:snippet_start,:snippet_end), 'pending',
               :generation
        FROM generate_series(1,2) AS candidate(slot)
        WHERE NOT EXISTS (SELECT 1 FROM practice.cards WHERE session_id=:session_id
                          AND cards.slot=candidate.slot)
        ORDER BY slot LIMIT 1
        ON CONFLICT (session_id, slot) DO NOTHING RETURNING id
    """),
            values,
        )
    ).first()
    return row[0] if row else None


def _card(row: object) -> schemas.Card:
    return schemas.Card.model_validate(row, from_attributes=True)


async def list_cards(
    db: AsyncSession, session_id: uuid.UUID | None, cursor: Cursor | None, limit: int
) -> list[schemas.Card]:
    rows = (
        await db.execute(
            text(f"""
        SELECT {_COLUMNS}, '/contents/' || s.content_id || '?at_ms=' || c.at_ms AS source_url
        FROM practice.cards c JOIN practice.sessions s ON s.id=c.session_id AND s.user_id=c.user_id
        WHERE s.deleting_at IS NULL
        AND (CAST(:session_id AS uuid) IS NULL OR c.session_id=:session_id)
        AND (CAST(:time AS timestamptz) IS NULL OR (c.created_at,c.id)<(:time,:id))
        ORDER BY c.created_at DESC, c.id DESC LIMIT :limit
    """),
            {
                "session_id": session_id,
                "time": cursor.created_at if cursor else None,
                "id": cursor.id if cursor else None,
                "limit": limit,
            },
        )
    ).all()
    return [_card(row) for row in rows]


async def get(db: AsyncSession, card_id: uuid.UUID) -> schemas.Card:
    row = (
        await db.execute(
            text(f"""
        SELECT {_COLUMNS}, '/contents/' || s.content_id || '?at_ms=' || c.at_ms AS source_url
        FROM practice.cards c JOIN practice.sessions s ON s.id=c.session_id AND s.user_id=c.user_id
        WHERE c.id=:id
    """),
            {"id": card_id},
        )
    ).one()
    return _card(row)


async def count(db: AsyncSession, session_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                text("SELECT count(*) FROM practice.cards WHERE session_id=:id"), {"id": session_id}
            )
        ).scalar_one()
    )


async def delete(db: AsyncSession, card_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            text(
                "DELETE FROM practice.cards c USING practice.sessions s WHERE c.id=:id "
                "AND s.id=c.session_id AND s.user_id=c.user_id AND s.deleting_at IS NULL "
                "RETURNING c.id"
            ),
            {"id": card_id},
        )
    ).first() is not None


async def audio_row(
    db: AsyncSession, card_id: uuid.UUID, learner: uuid.UUID, *, lock: bool = False
) -> Row[Any] | None:
    return (
        await db.execute(
            text(
                """
        SELECT c.*, s.content_id FROM practice.cards c JOIN practice.sessions s
        ON s.id=c.session_id AND s.user_id=c.user_id
        WHERE c.id=:id AND c.user_id=:user AND s.deleting_at IS NULL
    """
                + (" FOR UPDATE OF c" if lock else "")
            ),
            {"id": card_id, "user": learner},
        )
    ).first()


async def reviews(db: AsyncSession, card_id: uuid.UUID) -> schemas.ReviewHistory:
    rows = (
        await db.execute(
            text(
                "SELECT id,card_id,result,reviewed_at FROM practice.card_reviews "
                "WHERE card_id=:card ORDER BY reviewed_at DESC,id DESC LIMIT 50"
            ),
            {"card": card_id},
        )
    ).all()
    return schemas.ReviewHistory(
        reviews=[schemas.CardReview.model_validate(row, from_attributes=True) for row in rows]
    )


async def insert_review(
    db: AsyncSession, learner: uuid.UUID, card_id: uuid.UUID, review_id: uuid.UUID, result: str
) -> schemas.CardReview:
    row = (
        await db.execute(
            text(
                "INSERT INTO practice.card_reviews(id,card_id,user_id,result) "
                "VALUES (:id,:card,:user,:result) RETURNING id,card_id,result,reviewed_at"
            ),
            {"id": review_id, "card": card_id, "user": learner, "result": result},
        )
    ).one()
    return schemas.CardReview.model_validate(row, from_attributes=True)
