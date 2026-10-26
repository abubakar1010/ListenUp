"""Database Design 5; mirrors migration 77_shadow_segments."""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, TIMESTAMP, Range
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base


class ShadowSegment(Base):
    __tablename__ = "shadow_segments"
    __table_args__ = (
        CheckConstraint("chosen_by IN ('system', 'learner')"),
        CheckConstraint("mark_count >= 0"),
        CheckConstraint(
            "NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span) "
            "AND upper(span) - lower(span) BETWEEN 30000 AND 90000",
            name="shadow_segments_span",
        ),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.sessions.id", "practice.sessions.user_id"],
            name="shadow_segments_session_user_fk",
            ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "user_id", name="shadow_segments_session_user_uq"),
        {"schema": "practice"},
    )
    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    span: Mapped[Range[int]] = mapped_column(INT4RANGE)
    chosen_by: Mapped[Literal["system", "learner"]] = mapped_column(Text)
    mark_count: Mapped[int] = mapped_column(SmallInteger)
    locked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class ShadowRound(Base):
    __tablename__ = "shadow_rounds"
    __table_args__ = (
        CheckConstraint("round BETWEEN 1 AND 3"),
        CheckConstraint("playback_status IN ('ready','ended')"),
        UniqueConstraint("session_id", "round"),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.shadow_segments.session_id", "practice.shadow_segments.user_id"],
            name="shadow_rounds_segment_user_fk",
            ondelete="CASCADE",
        ),
        {"schema": "practice"},
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    round: Mapped[int] = mapped_column(SmallInteger)
    transcript_shown: Mapped[bool] = mapped_column(Computed("round = 1", persisted=True))
    playback_status: Mapped[Literal["ready", "ended"]] = mapped_column(Text, server_default="ready")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    recorded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
