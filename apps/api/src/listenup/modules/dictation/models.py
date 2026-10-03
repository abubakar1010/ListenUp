"""Tables owned by the dictation module (Database Design 5); migration 0010.

The table is created by the hand-written migration; this model mirrors it so that
`alembic check` reports drift. The trigger and the policy live only in the migration.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class DictationAttempt(Base):
    __tablename__ = "dictation_attempts"
    __table_args__ = (
        CheckConstraint("char_length(draft_text) <= 20000"),
        CheckConstraint("draft_version >= 0"),
        CheckConstraint("char_length(submitted_text) <= 20000"),
        CheckConstraint("scoring_status IN ('waiting_transcript', 'scored')"),
        CheckConstraint("accuracy BETWEEN 0 AND 100"),
        # The attempt together with its learner: never another learner's attempt.
        ForeignKeyConstraint(
            ["attempt_id", "user_id"],
            ["practice.attempts.id", "practice.attempts.user_id"],
            name="dictation_attempts_attempt_user_fk",
            ondelete="CASCADE",
        ),
        {"schema": "practice"},
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    draft_text: Mapped[str] = mapped_column(Text, server_default="")
    draft_version: Mapped[int] = mapped_column(Integer, server_default="0")
    submitted_text: Mapped[str | None] = mapped_column(Text)
    scoring_status: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    scored_at: Mapped[datetime | None] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
