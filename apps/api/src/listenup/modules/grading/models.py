"""Shared reference cache (Database Design 6; NFR-AI-4/5)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INT4RANGE, JSONB, TIMESTAMP, Range
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


class GistGrade(Base):
    __tablename__ = "gist_grades"
    __table_args__ = (
        CheckConstraint("status IN ('pending','ready','unavailable','delayed')"),
        CheckConstraint("overall BETWEEN 0 AND 100"),
        CheckConstraint("level IN ('needs_work','fair','good','excellent')"),
        CheckConstraint("char_length(feedback) BETWEEN 1 AND 1500"),
        CheckConstraint("length(rubric_version) > 0"),
        CheckConstraint("attempts_made >= 0"),
        CheckConstraint(
            "status <> 'ready' OR (overall IS NOT NULL AND level IS NOT NULL "
            "AND feedback IS NOT NULL AND rubric_version IS NOT NULL "
            "AND provider_info IS NOT NULL)",
            name="gist_grades_ready_complete",
        ),
        CheckConstraint(
            "provider_info IS NULL OR COALESCE(jsonb_typeof(provider_info) = 'object' "
            "AND provider_info ?& ARRAY['provider','model','version','prompt_version'] "
            "AND jsonb_typeof(provider_info->'provider') = 'string' "
            "AND length(provider_info->>'provider') > 0 "
            "AND jsonb_typeof(provider_info->'model') = 'string' "
            "AND length(provider_info->>'model') > 0 "
            "AND jsonb_typeof(provider_info->'version') = 'string' "
            "AND length(provider_info->>'version') > 0 "
            "AND jsonb_typeof(provider_info->'prompt_version') = 'string' "
            "AND length(provider_info->>'prompt_version') > 0, false)",
            name="gist_grades_provenance",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "user_id"],
            ["practice.attempts.id", "practice.attempts.user_id"],
            name="gist_grades_attempt_user_fk",
            ondelete="CASCADE",
        ),
        {"schema": "grading"},
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    key_points_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("grading.key_points.id", ondelete="SET NULL")
    )
    dimension_scores: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    overall: Mapped[int | None] = mapped_column(SmallInteger)
    level: Mapped[str | None] = mapped_column(Text)
    covered_points: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    wrong_claims: Mapped[list[str] | None] = mapped_column(JSONB)
    feedback: Mapped[str | None] = mapped_column(Text)
    rubric_version: Mapped[str | None] = mapped_column(Text)
    provider_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feedback_deadline: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    attempts_made: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class KeyPointDelay(Base):
    """Worker-only quota signal for an exact shared reference; contains no text."""

    __tablename__ = "key_point_delays"
    __table_args__ = ({"schema": "grading"},)

    media_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="CASCADE"), primary_key=True
    )
    span: Mapped[Range[int]] = mapped_column(INT4RANGE, primary_key=True)
    prompt_version: Mapped[str] = mapped_column(Text, primary_key=True)
