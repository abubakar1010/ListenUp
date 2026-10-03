"""The blind module's table (Database Design 5; migration 0009; ADR 0024).

The table lives in the practice schema beside `practice.attempts`, which it extends.
The migration creates it by hand; this model mirrors it so `alembic check` reports
drift. The fill factor and the row-level security policy live only in the migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class BlindAttempt(Base):
    __tablename__ = "blind_attempts"
    __table_args__ = (
        CheckConstraint("octet_length(media_token_hash) = 32"),
        CheckConstraint("passage_start_ms >= 0"),
        CheckConstraint("buffering_ms BETWEEN 0 AND 20000"),
        CheckConstraint("resume_count BETWEEN 0 AND 1"),
        CheckConstraint(
            "void_reason IN ('left_page', 'reload', 'seek', 'missed_heartbeat', 'too_fast', "
            "'interrupted')"
        ),
        CheckConstraint("char_length(gist_text) <= 2000"),
        CheckConstraint("passage_end_ms > passage_start_ms", name="blind_attempts_passage"),
        CheckConstraint(
            "(resume_count = 1) = (resume_stop_ms IS NOT NULL)", name="blind_attempts_resume_stop"
        ),
        ForeignKeyConstraint(
            ["attempt_id", "user_id"],
            ["practice.attempts.id", "practice.attempts.user_id"],
            name="blind_attempts_attempt_user_fk",
            ondelete="CASCADE",
        ),
        {"schema": "practice"},
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    media_token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    media_expires_at: Mapped[datetime] = mapped_column(Timestamp)
    passage_start_ms: Mapped[int] = mapped_column(Integer)
    passage_end_ms: Mapped[int] = mapped_column(Integer)
    last_position_ms: Mapped[int] = mapped_column(Integer)
    last_heartbeat_at: Mapped[datetime] = mapped_column(Timestamp)
    anchor_position_ms: Mapped[int] = mapped_column(Integer)
    anchor_at: Mapped[datetime] = mapped_column(Timestamp)
    buffering_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    resume_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    resume_stop_ms: Mapped[int | None] = mapped_column(Integer)
    void_reason: Mapped[str | None] = mapped_column(Text)
    gist_text: Mapped[str | None] = mapped_column(Text)
