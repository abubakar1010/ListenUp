"""Shared reference cache (Database Design 6; NFR-AI-4/5)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INT4RANGE, JSONB, TIMESTAMP, Range
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base


class KeyPoints(Base):
    __tablename__ = "key_points"
    __table_args__ = (
        CheckConstraint(
            "NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span) AND lower(span) >= 0"
        ),
        CheckConstraint("length(prompt_version) > 0"),
        CheckConstraint("grading.valid_key_points(points)"),
        CheckConstraint(
            "jsonb_typeof(provider_info) = 'object' "
            "AND provider_info ?& ARRAY['provider','model','version'] "
            "AND jsonb_typeof(provider_info->'provider') = 'string' "
            "AND length(provider_info->>'provider') > 0 "
            "AND jsonb_typeof(provider_info->'model') = 'string' "
            "AND length(provider_info->>'model') > 0 "
            "AND jsonb_typeof(provider_info->'version') = 'string' "
            "AND length(provider_info->>'version') > 0"
        ),
        UniqueConstraint("media_object_id", "span", "prompt_version"),
        {"schema": "grading"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    media_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="CASCADE")
    )
    span: Mapped[Range[int]] = mapped_column(INT4RANGE)
    prompt_version: Mapped[str] = mapped_column(Text)
    points: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    provider_info: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
