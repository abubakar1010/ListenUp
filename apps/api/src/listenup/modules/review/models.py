"""Tables owned by the review module (Database Design 5); migration 58_marks.

The table is created by the hand-written migration; this model mirrors it so that
`alembic check` reports drift. The policy lives only in the migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class Mark(Base):
    __tablename__ = "marks"
    __table_args__ = (
        CheckConstraint("word_from >= 0"),
        CheckConstraint("at_ms >= 0"),
        CheckConstraint("tag IN ('linking', 'reduction', 'weak_form', 'unknown_word')"),
        CheckConstraint("char_length(note) <= 500"),
        CheckConstraint("source IN ('dictation', 'manual')"),
        CheckConstraint("status IN ('suggested', 'confirmed')"),
        CheckConstraint("word_to >= word_from", name="marks_range_forward"),
        UniqueConstraint("session_id", "word_from", "word_to", name="marks_session_range_uq"),
        # The session together with its learner: never another learner's session.
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.sessions.id", "practice.sessions.user_id"],
            name="marks_session_user_fk",
            ondelete="CASCADE",
        ),
        Index("marks_session_idx", "session_id", "at_ms"),
        {"schema": "practice"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    word_from: Mapped[int] = mapped_column(Integer)
    word_to: Mapped[int] = mapped_column(Integer)
    at_ms: Mapped[int] = mapped_column(Integer)
    tag: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="confirmed")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
