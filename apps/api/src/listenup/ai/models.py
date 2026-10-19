"""AI operational tables, migration 0064_ai_gateway; no learner identity."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Double, Integer, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from listenup.platform.db import Base


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = ({"schema": "ai", "postgresql_partition_by": "RANGE (created_at)"},)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text)
    task: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    input_units: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_units: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    cache_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    audio_seconds: Mapped[float] = mapped_column(Double, server_default=text("0"))
    fallback_depth: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    queue_delay_ms: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    projected_cost_usd: Mapped[float] = mapped_column(Double, server_default=text("0"))
    usage_estimated: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    outcome: Mapped[str] = mapped_column(Text)


class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    __table_args__ = ({"schema": "ai"},)
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    calls: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    units: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    audio_seconds: Mapped[float] = mapped_column(Double, server_default=text("0"))
