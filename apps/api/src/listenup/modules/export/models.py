"""Table of the export module (`ops.data_exports`, migration 0012, ADR 0030)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base

Timestamp = TIMESTAMP(timezone=True)


class DataExport(Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'building', 'ready', 'failed', 'expired')"),
        CheckConstraint("char_length(archive_key) <= 300"),
        CheckConstraint("archive_bytes >= 0"),
        CheckConstraint("file_count >= 0"),
        CheckConstraint("char_length(error_code) <= 100"),
        CheckConstraint(
            "status <> 'ready' OR (archive_key IS NOT NULL AND ready_at IS NOT NULL "
            "AND expires_at IS NOT NULL)",
            name="data_exports_ready_has_archive",
        ),
        Index("data_exports_user_idx", "user_id", text("requested_at DESC"), "id"),
        Index(
            "data_exports_one_live",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'building')"),
        ),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    archive_key: Mapped[str | None] = mapped_column(Text)
    archive_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(Timestamp)
    expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
