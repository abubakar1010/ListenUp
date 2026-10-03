"""Tables of the practice schema owned by this module (Database Design 5); migration 0007.

The schema is created by the hand-written migration; these models mirror it so that
`alembic check` reports drift. Triggers and policies live only in the migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, TIMESTAMP, Range
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("upper(passage) - lower(passage) BETWEEN 30000 AND 900000"),
        CheckConstraint(
            "NOT isempty(passage) AND NOT lower_inf(passage) AND NOT upper_inf(passage) "
            "AND lower(passage) >= 0",
            name="sessions_passage_bounded",
        ),
        CheckConstraint("entry IN ('blind', 'dictation', 'both')"),
        CheckConstraint(
            "current_step IN ('blind', 'dictation', 'transcript', 'card', 'shadow', 'done')"
        ),
        CheckConstraint("status IN ('active', 'completed', 'abandoned')"),
        UniqueConstraint("id", "user_id", name="sessions_id_user_uq"),
        # A session practises the learner's own content item.
        ForeignKeyConstraint(
            ["content_id", "user_id"],
            ["content.contents.id", "content.contents.user_id"],
            name="sessions_content_user_fk",
            ondelete="CASCADE",
        ),
        Index("sessions_user_idx", "user_id", text("updated_at DESC"), "id"),
        Index("sessions_content_idx", "content_id"),
        {"schema": "practice"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    content_id: Mapped[uuid.UUID]
    passage: Mapped[Range[int]] = mapped_column(INT4RANGE)
    entry: Mapped[str] = mapped_column(Text)
    current_step: Mapped[str] = mapped_column(Text)
    entry_locked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    version: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp)


class SessionStep(Base):
    __tablename__ = "session_steps"
    __table_args__ = (
        CheckConstraint("step IN ('blind', 'dictation', 'transcript', 'card', 'shadow')"),
        CheckConstraint("position BETWEEN 1 AND 5"),
        CheckConstraint("status IN ('locked', 'open', 'done', 'skipped')"),
        CheckConstraint("status <> 'skipped' OR step IN ('card', 'shadow')"),
        UniqueConstraint("session_id", "position"),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.sessions.id", "practice.sessions.user_id"],
            name="session_steps_session_user_fk",
            ondelete="CASCADE",
        ),
        {"schema": "practice"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    step: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime | None] = mapped_column(Timestamp)
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp)
