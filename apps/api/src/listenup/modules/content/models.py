"""Tables of the content schema (Database Design 4); migration 0005."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class MediaObject(Base):
    __tablename__ = "media_objects"
    __table_args__ = (
        CheckConstraint("source IN ('youtube', 'upload')"),
        CheckConstraint("char_length(source_ref) <= 64"),
        CheckConstraint("char_length(title) <= 300"),
        CheckConstraint("duration_ms > 0"),
        CheckConstraint("status IN ('pending', 'downloading', 'playable', 'failed', 'expired')"),
        CheckConstraint("ref_count >= 0"),
        CheckConstraint("(source = 'upload') = (uploaded_by IS NOT NULL)"),
        Index(
            "media_objects_expiry_idx",
            "last_used_at",
            postgresql_where=text("status = 'playable' AND source = 'youtube'"),
        ),
        Index("media_objects_orphan_idx", "updated_at", postgresql_where=text("ref_count = 0")),
        Index(
            "media_objects_uploader_idx",
            "uploaded_by",
            postgresql_where=text("uploaded_by IS NOT NULL"),
        ),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE")
    )
    source_ref: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    has_video: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error_code: Mapped[str | None] = mapped_column(Text)
    playback_key: Mapped[str | None] = mapped_column(Text)
    video_key: Mapped[str | None] = mapped_column(Text)
    peaks_key: Mapped[str | None] = mapped_column(Text)
    playback_bytes: Mapped[int | None] = mapped_column(BigInteger)
    ref_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_used_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Content(Base):
    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 300"),
        UniqueConstraint("user_id", "media_object_id"),
        Index("contents_library_idx", "user_id", text("created_at DESC"), "id"),
        Index("contents_media_idx", "media_object_id"),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    media_object_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="NO ACTION")
    )
    title: Mapped[str] = mapped_column(Text)
    keep_video: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
