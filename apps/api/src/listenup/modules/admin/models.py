"""Tables of the admin module: takedown records (Database Design 7; migration 105)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class Takedown(Base):
    """A taken-down source, found by a fingerprint without a learner id (ADR 0098)."""

    __tablename__ = "takedowns"
    __table_args__ = (
        CheckConstraint("fingerprint ~ '^upload:[0-9a-f]{64}$'"),
        CheckConstraint("grounds IN ('copyright', 'other_rights', 'unlawful')"),
        CheckConstraint("char_length(reason) BETWEEN 1 AND 2000"),
        CheckConstraint("report IS NULL OR jsonb_typeof(report) = 'object'"),
        Index("takedowns_fingerprint_idx", "fingerprint", unique=True),
        Index(
            "takedowns_unactioned_idx",
            "received_at",
            postgresql_where=text("actioned_at IS NULL"),
        ),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    grounds: Mapped[str] = mapped_column(Text)
    # The administrator's note on the notice; never shown to a learner.
    reason: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    actioned_at: Mapped[datetime | None] = mapped_column(Timestamp)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
