"""Reads of the job queue for the admin view (#100, System Design 11.1), and takedown
records (#105, ADR 0098)."""

import uuid
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


# -- Takedowns (#105, ADR 0098) -------------------------------------------------------


@dataclass(frozen=True)
class TakedownRow:
    id: uuid.UUID
    fingerprint: str
    grounds: str
    received_at: datetime
    actioned_at: datetime | None


_TAKEDOWN_COLUMNS = "id, fingerprint, grounds, received_at, actioned_at"


async def insert_takedown(
    session: AsyncSession, takedown_id: uuid.UUID, fingerprint: str, grounds: str, reason: str
) -> TakedownRow | None:
    """The new record, or None when this source is already taken down."""
    row = (
        await session.execute(
            text(f"""
        INSERT INTO ops.takedowns (id, fingerprint, grounds, reason)
        VALUES (:id, :fingerprint, :grounds, :reason)
        ON CONFLICT (fingerprint) DO NOTHING
        RETURNING {_TAKEDOWN_COLUMNS}
        """),
            {"id": takedown_id, "fingerprint": fingerprint, "grounds": grounds, "reason": reason},
        )
    ).first()
    return TakedownRow(*row) if row else None


async def takedown_by_fingerprint(session: AsyncSession, fingerprint: str) -> TakedownRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_TAKEDOWN_COLUMNS} FROM ops.takedowns WHERE fingerprint = :fp"),
            {"fp": fingerprint},
        )
    ).first()
    return TakedownRow(*row) if row else None


async def takedown(session: AsyncSession, takedown_id: uuid.UUID) -> TakedownRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_TAKEDOWN_COLUMNS} FROM ops.takedowns WHERE id = :id"),
            {"id": takedown_id},
        )
    ).first()
    return TakedownRow(*row) if row else None


async def finish_takedown(
    session: AsyncSession,
    takedown_id: uuid.UUID,
    media_removed: int,
    learners: int,
    objects_removed: int,
) -> dict[str, int]:
    """Record that the takedown was carried out, with counts only (no learner ids).
    Objects add up over runs, since a repeated run finds nothing left to delete."""
    report: dict[str, int] = (
        await session.scalar(
            text("""
        UPDATE ops.takedowns
           SET actioned_at = coalesce(actioned_at, now()),
               report = jsonb_build_object(
                 'media_removed', CAST(:media AS int),
                 'learners', CAST(:learners AS int),
                 'objects_removed',
                   coalesce((report ->> 'objects_removed')::int, 0) + CAST(:objects AS int))
         WHERE id = :id
        RETURNING report
        """),
            {
                "id": takedown_id,
                "media": media_removed,
                "learners": learners,
                "objects": objects_removed,
            },
        )
    ) or {}
    return report


async def unactioned_takedowns(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.scalars(
        text("SELECT id FROM ops.takedowns WHERE actioned_at IS NULL ORDER BY received_at, id")
    )
    return list(rows.all())
