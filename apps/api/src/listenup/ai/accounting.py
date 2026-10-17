"""Independent, durable admission transactions. Never hold a DB lock during inference.

Reservations remain charged on uncertain failures/crashes. Only a successful result
with reported usage releases unused capacity; settlement is idempotent. Token totals
include reasoning/cache subsets once (ADR 0037).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.ai.config import ProviderEntry
from listenup.ai.models import Call, QuotaUsage
from listenup.ai.ports import Role, Usage
from listenup.platform.database import Database
from listenup.platform.ids import uuid7
from listenup.platform.telemetry import record_ai_quota

Outcome = Literal["ok", "invalid_output", "timeout", "error", "quota", "ineligible", "cancelled"]


@dataclass(frozen=True)
class Ticket:
    id: UUID
    created_at: datetime
    provider: str
    rates: tuple[float, float, float] = (0, 0, 0)


class Accounting(Protocol):
    async def admit(
        self,
        entry: ProviderEntry,
        role: Role,
        task: str,
        prompt: str | None,
        budget: Usage,
        routine: bool,
        *,
        fallback_depth: int = 0,
        queue_delay_ms: int = 0,
    ) -> Ticket | None: ...
    async def finish(
        self,
        ticket: Ticket,
        outcome: Outcome,
        latency_ms: int,
        version: str | None,
        usage: Usage | None,
    ) -> None: ...
    async def skip(
        self, entry: ProviderEntry, role: Role, task: str, prompt: str | None, outcome: Outcome
    ) -> None: ...
    async def remaining(self, entry: ProviderEntry) -> float: ...


def buckets(now: datetime) -> dict[str, datetime]:
    now = now.astimezone(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"minute": now.replace(second=0, microsecond=0), "day": day, "month": day.replace(day=1)}


def amount(row: QuotaUsage, dimension: str) -> float:
    return float(
        {"calls": row.calls, "tokens": row.units, "audio_seconds": row.audio_seconds}[dimension]
    )


def ratio(entry: ProviderEntry, rows: dict[str, QuotaUsage]) -> float:
    return min(
        (
            max(0.0, 1 - amount(rows[period], dim) / limit) if limit else 0.0
            for period, limits in entry.limits.items()
            if period != "minute"
            for dim, limit in limits.items()
        ),
        default=1.0,
    )


def projected_cost(usage: Usage, rates: tuple[float, float, float]) -> float:
    return (
        usage.input_tokens * rates[0] / 1_000_000
        + usage.output_tokens * rates[1] / 1_000_000
        + usage.audio_seconds * rates[2] / 3600
    )


class PostgresAccounting:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def _rows(
        self, session: AsyncSession, provider: str, now: datetime
    ) -> dict[str, QuotaUsage]:
        rows = {}
        for period, start in buckets(now).items():
            await session.execute(
                insert(QuotaUsage)
                .values(provider=provider, period=period, period_start=start)
                .on_conflict_do_nothing()
            )
            rows[period] = (
                await session.scalars(
                    select(QuotaUsage).where(
                        QuotaUsage.provider == provider,
                        QuotaUsage.period == period,
                        QuotaUsage.period_start == start,
                    )
                )
            ).one()
        return rows

    async def _lock(self, session: AsyncSession, provider: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:provider, 64))"),
            {"provider": provider},
        )

    async def _now(self, session: AsyncSession) -> datetime:
        return (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()  # type: ignore[no-any-return]

    async def admit(
        self,
        entry: ProviderEntry,
        role: Role,
        task: str,
        prompt: str | None,
        budget: Usage,
        routine: bool,
        *,
        fallback_depth: int = 0,
        queue_delay_ms: int = 0,
    ) -> Ticket | None:
        async with self.database.transaction() as session:
            await self._lock(session, entry.provider)
            now = await self._now(session)
            rows = await self._rows(session, entry.provider, now)
            increments = {
                "calls": 1,
                "tokens": budget.tokens,
                "audio_seconds": budget.audio_seconds,
            }
            allowed = all(
                amount(rows[period], dim) + increments[dim]
                <= limit
                * (
                    1 - entry.grading_reserve
                    if routine and not entry.local and period != "minute"
                    else 1
                )
                for period, limits in entry.limits.items()
                for dim, limit in limits.items()
            )
            call = self._call(
                entry,
                role,
                task,
                prompt,
                now,
                "pending" if allowed else "quota",
                budget if allowed else Usage(),
            )
            call.fallback_depth, call.queue_delay_ms = fallback_depth, queue_delay_ms
            rates = (
                entry.projected_input_cost_per_million,
                entry.projected_output_cost_per_million,
                entry.projected_audio_cost_per_hour,
            )
            call.projected_cost_usd = projected_cost(budget, rates) if allowed else 0
            session.add(call)
            if allowed:
                for row in rows.values():
                    row.calls += 1
                    row.units += budget.tokens
                    row.audio_seconds += budget.audio_seconds
            record_ai_quota(entry.provider, ratio(entry, rows))
        return Ticket(call.id, now, entry.provider, rates) if allowed else None

    @staticmethod
    def _call(
        entry: ProviderEntry,
        role: Role,
        task: str,
        prompt: str | None,
        now: datetime,
        outcome: str,
        budget: Usage,
    ) -> Call:
        return Call(
            id=uuid7(),
            created_at=now,
            role=role.value,
            task=task,
            provider=entry.provider,
            model=entry.model,
            prompt_version=prompt,
            outcome=outcome,
            input_units=budget.input_tokens,
            output_units=budget.output_tokens,
            reasoning_tokens=budget.reasoning_tokens,
            cache_tokens=budget.cache_tokens,
            audio_seconds=budget.audio_seconds,
        )

    async def finish(
        self,
        ticket: Ticket,
        outcome: Outcome,
        latency_ms: int,
        version: str | None,
        usage: Usage | None,
    ) -> None:
        async with self.database.transaction() as session:
            await self._lock(session, ticket.provider)
            call = await session.get(Call, (ticket.id, ticket.created_at))
            if call is None or call.outcome != "pending":
                return
            if outcome == "ok" and usage is not None:
                rows = await self._rows(session, ticket.provider, ticket.created_at)
                for row in rows.values():
                    row.units += usage.tokens - call.input_units - call.output_units
                    row.audio_seconds += usage.audio_seconds - call.audio_seconds
                call.input_units, call.output_units = usage.input_tokens, usage.output_tokens
                call.reasoning_tokens, call.cache_tokens = (
                    usage.reasoning_tokens,
                    usage.cache_tokens,
                )
                call.audio_seconds = usage.audio_seconds
                call.projected_cost_usd = projected_cost(usage, ticket.rates)
                call.usage_estimated = False
            call.outcome, call.latency_ms, call.version = outcome, latency_ms, version

    async def skip(
        self, entry: ProviderEntry, role: Role, task: str, prompt: str | None, outcome: Outcome
    ) -> None:
        async with self.database.transaction() as session:
            now = await self._now(session)
            session.add(self._call(entry, role, task, prompt, now, outcome, Usage()))

    async def remaining(self, entry: ProviderEntry) -> float:
        async with self.database.transaction() as session:
            await self._lock(session, entry.provider)
            rows = await self._rows(session, entry.provider, await self._now(session))
            value = ratio(entry, rows)
            record_ai_quota(entry.provider, value)
            return value
