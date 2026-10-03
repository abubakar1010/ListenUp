"""Tables of the ops schema owned by the platform package (Database Design 7)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class RateCounter(Base):
    __tablename__ = "rate_counters"
    __table_args__ = (
        CheckConstraint("char_length(key) <= 200"),
        Index("rate_counters_window_idx", "window_start"),
        {"schema": "ops", "prefixes": ["UNLOGGED"]},
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(Timestamp, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default="0")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("char_length(key) BETWEEN 1 AND 100"),
        Index("idempotency_keys_age_idx", "created_at"),
        {"schema": "ops"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
