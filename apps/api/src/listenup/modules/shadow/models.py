"""Database Design 5; mirrors migration 77_shadow_segments."""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
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
        CheckConstraint(
            "recording_key IS NULL OR (char_length(recording_key) <= 300 "
            "AND recording_key LIKE 'users/' || user_id::text || '/shadow/%' "
            "AND recording_mime IN ('audio/webm','audio/mp4') "
            "AND recording_bytes BETWEEN 1 AND 5242880)",
            name="shadow_rounds_recording_private",
        ),
        CheckConstraint(
            "(recording_key IS NULL) = (recording_mime IS NULL) "
            "AND (recording_key IS NULL) = (recording_bytes IS NULL)",
            name="shadow_rounds_recording_all_or_none",
        ),
        CheckConstraint(
            "uploaded_at IS NULL OR (recording_key IS NOT NULL AND recorded_at IS NOT NULL)",
            name="shadow_rounds_uploaded",
        ),
        Index(
            "shadow_rounds_expiry_idx",
            "recorded_at",
            postgresql_where=text("recording_key IS NOT NULL"),
        ),
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
    recording_key: Mapped[str | None] = mapped_column(Text)
    recording_mime: Mapped[str | None] = mapped_column(Text)
    recording_bytes: Mapped[int | None]
    uploaded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
