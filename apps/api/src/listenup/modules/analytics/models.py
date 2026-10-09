"""Table of the analytics module (`ops.analytics_events`, migration 0015, ADR 0033).

The schema is created by the hand-written migration; this model mirrors it so that
`alembic check` reports drift. The policies live only in the migration.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('content_added', 'plan_started', 'step_started', 'step_completed', "
            "'listen_started', 'dictation_replays', 'blind_abandoned', 'mark_created', "
            "'card_created', 'shadow_round_completed')"
        ),
        CheckConstraint("step IN ('blind', 'dictation', 'transcript', 'card', 'shadow')"),
        CheckConstraint(
            "jsonb_typeof(properties) = 'object' AND pg_column_size(properties) <= 1000"
        ),
        CheckConstraint(
            "(step IS NOT NULL) = (event_type IN ('step_started', 'step_completed'))",
            name="analytics_events_step_events_have_a_step",
        ),
        UniqueConstraint(
            "event_type",
            "subject_id",
            "step",
            name="analytics_events_once",
            postgresql_nulls_not_distinct=True,
        ),
        Index("analytics_events_type_time_idx", "event_type", "occurred_at"),
        Index("analytics_events_user_idx", "user_id", "occurred_at"),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID]
    step: Mapped[str | None] = mapped_column(Text)
    content_id: Mapped[uuid.UUID | None]
    session_id: Mapped[uuid.UUID | None]
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    occurred_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
