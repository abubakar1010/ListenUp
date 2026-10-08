"""Reads of the job queue for the admin view (#100, System Design 11.1)."""

from dataclasses import dataclass

from sqlalchemy import text
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
