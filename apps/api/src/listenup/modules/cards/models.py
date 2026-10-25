"""Migration 72_cards mirrors (ADR 0013)."""

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


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("slot IN (1, 2)"),
        CheckConstraint("at_ms >= 0"),
        CheckConstraint("char_length(written_form) BETWEEN 1 AND 100"),
        CheckConstraint("char_length(heard_form) BETWEEN 1 AND 100"),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.sessions.id", "practice.sessions.user_id"],
            name="cards_session_user_fk",
            ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "slot"),
        Index("cards_user_idx", "user_id", text("created_at DESC"), "id"),
        {"schema": "practice"},
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    slot: Mapped[int] = mapped_column(SmallInteger)
    mark_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice.marks.id", ondelete="SET NULL")
    )
    media_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="SET NULL")
    )
    at_ms: Mapped[int] = mapped_column(Integer)
    written_form: Mapped[str] = mapped_column(Text)
    heard_form: Mapped[str] = mapped_column(Text)
    snippet_key: Mapped[str | None] = mapped_column(Text)
    snippet_span: Mapped[Range[int] | None] = mapped_column(INT4RANGE)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
