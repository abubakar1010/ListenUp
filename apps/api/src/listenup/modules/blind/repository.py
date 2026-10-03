"""SQL for practice.blind_attempts (migration 0009).

Statements run in the request's transaction as the API role, so row-level security
limits them to the current learner. A heartbeat reads its row with FOR UPDATE and
writes it back once, so two beats of one attempt never interleave.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.blind.domain import Listen


@dataclass(frozen=True)
class BlindRow:
    attempt_id: uuid.UUID
    user_id: uuid.UUID
    media_token_hash: bytes
    media_expires_at: datetime
    listen: Listen
    void_reason: str | None
    gist_text: str | None


_COLUMNS = """attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms,
    passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms, anchor_at,
    buffering_ms, resume_count, resume_stop_ms, void_reason, gist_text"""


def _row(row: Row[Any]) -> BlindRow:
    return BlindRow(
        attempt_id=row.attempt_id,
        user_id=row.user_id,
        media_token_hash=bytes(row.media_token_hash),
        media_expires_at=row.media_expires_at,
        listen=Listen(
            passage_start_ms=row.passage_start_ms,
            passage_end_ms=row.passage_end_ms,
            last_position_ms=row.last_position_ms,
            last_heartbeat_at=row.last_heartbeat_at,
            anchor_position_ms=row.anchor_position_ms,
            anchor_at=row.anchor_at,
            buffering_ms=row.buffering_ms,
            resume_count=row.resume_count,
            resume_stop_ms=row.resume_stop_ms,
        ),
        void_reason=row.void_reason,
        gist_text=row.gist_text,
    )


def _listen_params(listen: Listen) -> dict[str, object]:
    return {
        "last_position_ms": listen.last_position_ms,
        "last_heartbeat_at": listen.last_heartbeat_at,
        "anchor_position_ms": listen.anchor_position_ms,
        "anchor_at": listen.anchor_at,
        "buffering_ms": listen.buffering_ms,
        "resume_count": listen.resume_count,
        "resume_stop_ms": listen.resume_stop_ms,
    }


async def insert(
    db: AsyncSession,
    attempt_id: uuid.UUID,
    user_id: uuid.UUID,
    media_token_hash: bytes,
    listen: Listen,
) -> BlindRow:
    row = (
        await db.execute(
            text(f"""
            INSERT INTO practice.blind_attempts (
              attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms,
              passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms,
              anchor_at, buffering_ms, resume_count, resume_stop_ms)
            VALUES (
              :attempt_id, :user_id, :media_token_hash, :media_expires_at, :passage_start_ms,
              :passage_end_ms, :last_position_ms, :last_heartbeat_at, :anchor_position_ms,
              :anchor_at, :buffering_ms, :resume_count, :resume_stop_ms)
            RETURNING {_COLUMNS}
            """),
            {
                "attempt_id": attempt_id,
                "user_id": user_id,
                "media_token_hash": media_token_hash,
                "media_expires_at": listen.media_deadline(),
                "passage_start_ms": listen.passage_start_ms,
                "passage_end_ms": listen.passage_end_ms,
                **_listen_params(listen),
            },
        )
    ).one()
    return _row(row)


async def get(db: AsyncSession, attempt_id: uuid.UUID, *, lock: bool = False) -> BlindRow | None:
    row = (
        await db.execute(
            text(
                f"SELECT {_COLUMNS} FROM practice.blind_attempts WHERE attempt_id = :id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"id": attempt_id},
        )
    ).first()
    return _row(row) if row else None


async def save(
    db: AsyncSession,
    attempt_id: uuid.UUID,
    listen: Listen,
    *,
    void_reason: str | None = None,
    gist_text: str | None = None,
) -> BlindRow:
    """Write the listen back, with a void reason or the gist when there is one.

    The media deadline only ever moves later (a resume extends it).
    """
    row = (
        await db.execute(
            text(f"""
            UPDATE practice.blind_attempts
               SET last_position_ms = :last_position_ms,
                   last_heartbeat_at = :last_heartbeat_at,
                   anchor_position_ms = :anchor_position_ms,
                   anchor_at = :anchor_at,
                   buffering_ms = :buffering_ms,
                   resume_count = :resume_count,
                   resume_stop_ms = :resume_stop_ms,
                   media_expires_at = greatest(media_expires_at, :media_expires_at),
                   void_reason = coalesce(:void_reason, void_reason),
                   gist_text = coalesce(:gist_text, gist_text)
             WHERE attempt_id = :attempt_id
            RETURNING {_COLUMNS}
            """),
            {
                "attempt_id": attempt_id,
                "media_expires_at": listen.media_deadline(),
                "void_reason": void_reason,
                "gist_text": gist_text,
                **_listen_params(listen),
            },
        )
    ).one()
    return _row(row)
