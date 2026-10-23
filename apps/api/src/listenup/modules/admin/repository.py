"""Reads of the job queue for the admin view (#100, System Design 11.1)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LaneRow:
    lane: str
    waiting: int
    scheduled: int
    running: int
    oldest_wait_seconds: float | None


async def lane_backlog(session: AsyncSession) -> dict[str, LaneRow]:
    """Jobs per lane that are due and waiting, scheduled for later (a retry's backoff or
    a postponed start), and running; lanes with no jobs are missing."""
    rows = await session.execute(
        text("""
        SELECT j.queue_name AS lane,
               count(*) FILTER (WHERE j.status = 'todo' AND coalesce(j.scheduled_at <= now(), true))
                 AS waiting,
               count(*) FILTER (WHERE j.status = 'todo' AND j.scheduled_at > now()) AS scheduled,
               count(*) FILTER (WHERE j.status = 'doing') AS running,
               extract(epoch FROM now() - min(coalesce(j.scheduled_at, d.at))
                 FILTER (WHERE j.status = 'todo' AND coalesce(j.scheduled_at <= now(), true)))
                 AS oldest_wait_seconds
          FROM procrastinate.procrastinate_jobs j
          LEFT JOIN LATERAL (
            SELECT min(e.at) AS at FROM procrastinate.procrastinate_events e
             WHERE e.job_id = j.id AND e.type = 'deferred'
          ) d ON j.status = 'todo'
         WHERE j.status IN ('todo', 'doing')
         GROUP BY j.queue_name
        """)
    )
    return {
        row.lane: LaneRow(
            row.lane,
            row.waiting,
            row.scheduled,
            row.running,
            float(row.oldest_wait_seconds) if row.oldest_wait_seconds is not None else None,
        )
        for row in rows
    }


async def usage_rows(
    session: AsyncSession, since: datetime, now: datetime, today: datetime, month: datetime
) -> tuple[Sequence[RowMapping], Sequence[RowMapping]]:
    """Two independent aggregates in one restricted, read-only snapshot."""
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    await session.execute(text("SET LOCAL ROLE listenup_readonly"))
    daily = (
        (
            await session.execute(
                text("""
        SELECT provider, (created_at AT TIME ZONE 'UTC')::date AS date,
               count(*) AS calls, sum(input_units) AS input_tokens,
               sum(output_units) AS output_tokens, sum(audio_seconds) AS audio_seconds,
               sum(projected_cost_usd) AS estimated_cost_usd,
               count(*) FILTER (WHERE usage_estimated) AS estimated_calls
          FROM ai.calls
         WHERE created_at >= :since AND created_at <= :now
           AND outcome NOT IN ('quota', 'ineligible')
         GROUP BY provider, (created_at AT TIME ZONE 'UTC')::date
         ORDER BY provider, date
    """),
                {"since": since, "now": now},
            )
        )
        .mappings()
        .all()
    )
    quotas = (
        (
            await session.execute(
                text("""
        SELECT provider, period, calls, units AS tokens, audio_seconds
          FROM ai.quota_usage
         WHERE (period = 'day' AND period_start = :today)
            OR (period = 'month' AND period_start = :month)
    """),
                {"today": today, "month": month},
            )
        )
        .mappings()
        .all()
    )
    return daily, quotas
