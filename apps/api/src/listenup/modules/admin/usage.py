"""Aggregate-only usage reports (SRS 2.2, NFR-AI-10).

Reads the effective configuration's quota metadata without importing the AI layer,
constructing providers or returning provider options. Never changes AI accounting.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from listenup.modules.admin import repository
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError

Limit = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Dimension = Literal["calls", "tokens", "audio_seconds"]
Period = Literal["day", "month"]


class QuotaProvider(BaseModel):
    provider: str = Field(min_length=1)
    limits: dict[Literal["minute", "day", "month"], dict[Dimension, Limit]] = Field(
        default_factory=dict
    )


class QuotaConfiguration(BaseModel):
    roles: dict[str, list[QuotaProvider]]


def quota_limits(path: str | None) -> dict[str, dict[Period, dict[Dimension, float]]]:
    target = Path(path) if path else Path(__file__).resolve().parents[2] / "ai" / "ai.yaml"
    config = QuotaConfiguration.model_validate(yaml.safe_load(target.read_text()))
    limits: dict[str, dict[Period, dict[Dimension, float]]] = {}
    for entries in config.roles.values():
        for entry in entries:
            selected: dict[Period, dict[Dimension, float]] = {
                p: entry.limits.get(p, {}) for p in ("day", "month")
            }
            if entry.provider in limits and limits[entry.provider] != selected:
                raise ValueError("conflicting provider quota limits")
            limits[entry.provider] = selected
    return limits


class DailyUsage(BaseModel):
    date: date
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0
    estimated_cost_usd: float = Field(
        default=0, description="Stored hypothetical cost, not billed spend"
    )
    estimated_calls: int = Field(default=0, description="Calls retaining estimated/reserved usage")


class QuotaUsage(BaseModel):
    period: Period
    calls: int = 0
    tokens: int = 0
    audio_seconds: float = 0
    limits: dict[Dimension, float] | None = Field(
        description="Current configured allowance; absent dimension is uncapped, null is unknown",
    )


class ProviderUsage(BaseModel):
    provider: str
    days: list[DailyUsage]
    quotas: list[QuotaUsage]


class UsageOverview(BaseModel):
    start_date: date
    end_date: date
    as_of: datetime
    providers: list[ProviderUsage]


async def usage_overview(
    database: Database | None, path: str | None, now: datetime
) -> UsageOverview:
    """One read-only snapshot; access is checked before this function is called.

    The report connection must be able to assume listenup_readonly. Never retry a
    failed report with the API/worker/owner connection or expose connection/config errors.
    """
    if database is None:
        raise ProblemError(503, "usage_unavailable", "Usage reporting is unavailable.")
    now = now.astimezone(UTC)
    end = now.date()
    start = end - timedelta(days=29)
    since = datetime.combine(start, datetime.min.time(), UTC)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        limits = quota_limits(path)
        async with database.transaction() as session:
            daily, quotas = await repository.usage_rows(session, since, now, today, month)
    except (OSError, ValueError, yaml.YAMLError, SQLAlchemyError):
        raise ProblemError(503, "usage_unavailable", "Usage reporting is unavailable.") from None
    providers = sorted(
        set(limits) | {r["provider"] for r in daily} | {r["provider"] for r in quotas}
    )
    by_day = {(r["provider"], r["date"]): dict(r) for r in daily}
    by_period = {(r["provider"], r["period"]): dict(r) for r in quotas}
    dates = [start + timedelta(days=offset) for offset in range(30)]
    return UsageOverview(
        start_date=start,
        end_date=end,
        as_of=now,
        providers=[
            ProviderUsage(
                provider=provider,
                days=[
                    DailyUsage.model_validate(by_day.get((provider, day), {"date": day}))
                    for day in dates
                ],
                quotas=[
                    QuotaUsage.model_validate(
                        {
                            **by_period.get((provider, period), {"period": period}),
                            "limits": limits.get(provider, {}).get(period),
                        }
                    )
                    for period in ("day", "month")
                ],
            )
            for provider in providers
        ],
    )
