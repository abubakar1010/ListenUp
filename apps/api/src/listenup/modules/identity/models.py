"""Tables of the identity schema (Database Design section 3)."""

import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(email) <= 254"),
        CheckConstraint("char_length(display_name) <= 80"),
        CheckConstraint("status IN ('active', 'pending_deletion', 'deleting')"),
        # DR-1: a pending deletion always has its date, and nothing else has one.
        CheckConstraint("(status = 'pending_deletion') = (deletion_scheduled_at IS NOT NULL)"),
        Index(
            "users_deletion_due_idx",
            "deletion_scheduled_at",
            postgresql_where=text("status = 'pending_deletion'"),
        ),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(Timestamp)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("char_length(user_agent) <= 400"),
        Index("auth_sessions_user_idx", "user_id"),
        Index("auth_sessions_expires_idx", "expires_at"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)  # SHA-256 of the cookie
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)


class OneTimeToken(Base):
    __tablename__ = "one_time_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify_email', 'reset_password')"),
        Index("one_time_tokens_user_idx", "user_id", "purpose"),
        {"schema": "identity"},
    )

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)  # SHA-256
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class DeletionRequest(Base):
    """A deletion and its audit record (Database Design 7, 10.1; ADR 0029).

    Account requests are written when the learner deletes the account and purged by
    the background job once `due_at` passes, unless a restore cancelled them. No
    foreign key: the row outlives the account it deletes.
    """

    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint("scope IN ('account', 'content', 'session', 'recordings')"),
        CheckConstraint(
            "status IN ('pending', 'storage_deleted', 'completed', 'failed', 'cancelled')"
        ),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)"),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)"),
        CheckConstraint("(status = 'failed') = (failed_at IS NOT NULL)"),
        CheckConstraint("due_at >= requested_at"),
        Index(
            "deletion_requests_due_idx",
            "due_at",
            postgresql_where=text("status IN ('pending', 'storage_deleted', 'failed')"),
        ),
        Index(
            "deletion_requests_one_open_account_idx",
            "subject_user_id",
            unique=True,
            postgresql_where=text(
                "scope = 'account' AND status IN ('pending', 'storage_deleted', 'failed')"
            ),
        ),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    subject_user_id: Mapped[uuid.UUID]
    scope: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    storage_prefixes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    media_object_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID), server_default="{}")
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    requested_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    due_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(Timestamp)
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    failed_at: Mapped[datetime | None] = mapped_column(Timestamp)
