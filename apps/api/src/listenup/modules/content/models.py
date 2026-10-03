"""Tables of the content schema (Database Design 4); migration 0005."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
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
    # How far the conversion job has got while the item is prepared (migration 0011).
    stage: Mapped[str | None] = mapped_column(Text)
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
        # Lets practice sessions reference (content id, learner) together (migration 0007).
        UniqueConstraint("id", "user_id", name="contents_id_user_uq"),
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


class Upload(Base):
    """A file the learner is uploading straight to storage (migration 0006, ADR 0020)."""

    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint("char_length(filename) BETWEEN 1 AND 255"),
        CheckConstraint("char_length(content_type) BETWEEN 1 AND 100"),
        CheckConstraint("size_bytes > 0"),
        CheckConstraint("(confirmed_at IS NULL) = (content_id IS NULL)"),
        CheckConstraint("(content_id IS NULL) = (media_object_id IS NULL)"),
        Index("uploads_user_idx", "user_id", "created_at"),
        Index(
            "uploads_unconfirmed_idx",
            "created_at",
            postgresql_where=text("confirmed_at IS NULL"),
        ),
        Index(
            "uploads_waiting_idx",
            "user_id",
            "confirmed_at",
            "id",
            postgresql_where=text("confirmed_at IS NOT NULL AND queued_at IS NULL"),
        ),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content.contents.id", ondelete="CASCADE"), unique=True
    )
    media_object_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content.media_objects.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    # When its conversion went on the shared intake lane; NULL while it waits in the
    # learner's own queue (migration 0011, ADR 0027).
    queued_at: Mapped[datetime | None] = mapped_column(Timestamp)


class DuplicateUpload(Base):
    """An item removed as a copy of one the learner already had (migration 0011)."""

    __tablename__ = "duplicate_uploads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["existing_content_id", "user_id"],
            ["content.contents.id", "content.contents.user_id"],
            ondelete="CASCADE",
        ),
        Index("duplicate_uploads_existing_idx", "existing_content_id", "user_id"),
        {"schema": "content"},
    )

    content_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    existing_content_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
