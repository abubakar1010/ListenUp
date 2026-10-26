"""Shared transcript cache and learner-owned overlays (Database Design 4)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    INT4RANGE,
    JSONB,
    TIMESTAMP,
    ExcludeConstraint,
    Range,
)
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base


class PassageTranscript(Base):
    __tablename__ = "passage_transcripts"
    __table_args__ = (
        CheckConstraint(
            "NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span) AND lower(span) >= 0"
        ),
        CheckConstraint("origin IN ('creator_captions', 'generated')"),
        CheckConstraint("status IN ('pending', 'ready', 'failed')"),
        CheckConstraint(
            "cardinality(words) = cardinality(start_ms) AND cardinality(words) = "
            "cardinality(end_ms) AND cardinality(words) = cardinality(confidence)"
        ),
        CheckConstraint(
            "array_position(confidence, NULL) IS NULL "
            "AND 0 <= ALL(confidence) AND 1000 >= ALL(confidence)"
        ),
        CheckConstraint(
            "array_position(sentence_starts, NULL) IS NULL "
            "AND 0 <= ALL(sentence_starts) AND cardinality(words) > ALL(sentence_starts)"
        ),
        CheckConstraint(
            "status <> 'ready' OR (jsonb_typeof(provider_info) = 'object' "
            "AND provider_info ?& ARRAY['provider','model','version'] "
            "AND jsonb_typeof(provider_info->'provider') = 'string' "
            "AND length(provider_info->>'provider') > 0 "
            "AND jsonb_typeof(provider_info->'model') = 'string' "
            "AND length(provider_info->>'model') > 0 "
            "AND jsonb_typeof(provider_info->'version') = 'string' "
            "AND length(provider_info->>'version') > 0)"
        ),
        ExcludeConstraint(
            ("media_object_id", "="), ("span", "&&"), using="gist", where=text("status <> 'failed'")
        ),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    media_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="CASCADE")
    )
    span: Mapped[Range[int]] = mapped_column(INT4RANGE)
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    words: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    start_ms: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    end_ms: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    confidence: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default="{}")
    sentence_starts: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    provider_info: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    @property
    def bounds(self) -> tuple[int, int]:
        # The migration rejects infinite and empty ranges.
        assert self.span.lower is not None and self.span.upper is not None
        return self.span.lower, self.span.upper


class TranscriptCorrection(Base):
    __tablename__ = "transcript_corrections"
    __table_args__ = (
        CheckConstraint("word_index >= 0"),
        CheckConstraint("char_length(corrected_text) BETWEEN 0 AND 60"),
        {"schema": "content"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    passage_transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.passage_transcripts.id", ondelete="CASCADE"), primary_key=True
    )
    word_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    corrected_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ReferenceProfile(Base):
    """One limited profile per original transcript span and processing recipe (#76)."""

    __tablename__ = "reference_profiles"
    __table_args__ = (
        CheckConstraint(
            "status <> 'ready' OR COALESCE(jsonb_typeof(provenance->'alignment'->'provider') = "
            "'string' AND length(provenance->'alignment'->>'provider') > 0 AND "
            "jsonb_typeof(provenance->'alignment'->'model') = 'string' AND "
            "length(provenance->'alignment'->>'model') > 0 AND "
            "jsonb_typeof(provenance->'alignment'->'version') = 'string' AND "
            "length(provenance->'alignment'->>'version') > 0 AND "
            "jsonb_typeof(provenance->'acoustics'->'provider') = 'string' AND "
            "length(provenance->'acoustics'->>'provider') > 0 AND "
            "jsonb_typeof(provenance->'acoustics'->'model') = 'string' AND "
            "length(provenance->'acoustics'->>'model') > 0 AND "
            "jsonb_typeof(provenance->'acoustics'->'version') = 'string' AND "
            "length(provenance->'acoustics'->>'version') > 0 AND "
            "jsonb_typeof(provenance->'acoustics'->'praat_version') = 'string' AND "
            "length(provenance->'acoustics'->>'praat_version') > 0 AND "
            "jsonb_typeof(provenance->'acoustics'->'settings') = 'object', false) ",
            name="reference_profiles_provenance_types",
        ),
        CheckConstraint("status IN ('pending','ready','failed')"),
        CheckConstraint("length(fingerprint) = 64"),
        CheckConstraint("frame_step_ms = 20"),
        CheckConstraint(
            "cardinality(word_indices) = cardinality(word_start_ms) AND "
            "cardinality(word_indices) = cardinality(word_end_ms) AND "
            "cardinality(word_indices) = cardinality(word_confidence)"
        ),
        CheckConstraint("array_position(word_indices, NULL) IS NULL AND 0 <= ALL(word_indices)"),
        CheckConstraint("array_position(word_start_ms, NULL) IS NULL AND 0 <= ALL(word_start_ms)"),
        CheckConstraint("array_position(word_end_ms, NULL) IS NULL AND 0 <= ALL(word_end_ms)"),
        CheckConstraint(
            "array_position(word_confidence, NULL) IS NULL AND 0 <= "
            "ALL(word_confidence) AND 1000 >= ALL(word_confidence)"
        ),
        CheckConstraint("cardinality(pitch_cents) = cardinality(intensity_cdb)"),
        CheckConstraint(
            "status <> 'ready' OR (cardinality(pitch_cents) > 0 AND "
            "COALESCE(jsonb_typeof(provenance) = 'object' AND provenance ?& "
            "ARRAY['alignment','acoustics','format_version'] AND "
            "provenance->>'format_version' = '1' AND "
            "jsonb_typeof(provenance->'alignment') = 'object' AND "
            "provenance->'alignment' ?& ARRAY['provider','model','version'] AND "
            "jsonb_typeof(provenance->'acoustics') = 'object' AND "
            "provenance->'acoustics' ?& "
            "ARRAY['provider','model','version','praat_version','settings'] AND "
            "length(provenance->'alignment'->>'provider') > 0 AND "
            "length(provenance->'alignment'->>'model') > 0 AND "
            "length(provenance->'alignment'->>'version') > 0 AND "
            "length(provenance->'acoustics'->>'version') > 0, false))"
        ),
        {"schema": "content"},
    )

    passage_transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.passage_transcripts.id", ondelete="CASCADE"), primary_key=True
    )
    fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    word_indices: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    word_start_ms: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    word_end_ms: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    word_confidence: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default="{}")
    pitch_cents: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger), server_default="{}")
    intensity_cdb: Mapped[list[int | None]] = mapped_column(
        ARRAY(SmallInteger), server_default="{}"
    )
    frame_step_ms: Mapped[int] = mapped_column(SmallInteger, server_default="20")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ProfileSubscription(Base):
    """Durable per-session readiness; cache rows themselves never belong to a learner."""

    __tablename__ = "profile_subscriptions"
    __table_args__ = (
        Index("profile_subscriptions_media_idx", "media_object_id"),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["practice.sessions.id", "practice.sessions.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status IN ('pending','ready','failed')"),
        CheckConstraint("length(fingerprint) = 64"),
        CheckConstraint(
            "NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span) AND lower(span) >= 0"
        ),
        {"schema": "content"},
    )
    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column()
    media_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="CASCADE")
    )
    span: Mapped[Range[int]] = mapped_column(INT4RANGE)
    fingerprint: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
