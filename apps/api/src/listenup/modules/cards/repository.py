"""Cards SQL, always under learner RLS in the request transaction."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.cards import schemas
from listenup.modules.cards.domain.cursor import Cursor

_COLUMNS = (
    "c.id, c.session_id, c.slot, c.mark_id, c.written_form, c.heard_form, "
    "c.at_ms, c.created_at, s.content_id"
)


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
                                   at_ms, written_form, heard_form)
        SELECT :id, :session_id, :user_id, slot, :mark_id, :media_object_id, :at_ms,
               :written_form, :heard_form
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
        WHERE (CAST(:session_id AS uuid) IS NULL OR c.session_id=:session_id)
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
            text("DELETE FROM practice.cards WHERE id=:id RETURNING id"), {"id": card_id}
        )
    ).first() is not None
