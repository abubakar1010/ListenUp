"""Delayed cleanup for Blind attempts whose browser stopped sending heartbeats."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.blind import repository
from listenup.modules.blind.domain import Listen, VoidReason
from listenup.modules.practice import service as practice
from listenup.modules.practice.service import AttemptStatus, Step
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.events import EventType as LiveEventType
from listenup.platform.events import publish
from listenup.platform.jobs import JobDeps, Lane, enqueue, job

EXPIRE_ATTEMPT = "blind.expire_attempt"


async def queue_expiry(session: AsyncSession, attempt_id: uuid.UUID, listen: Listen) -> None:
    """Queue one check for this version of the attempt's heartbeat deadline."""
    due = listen.abandonment_deadline()
    await enqueue(
        session,
        EXPIRE_ATTEMPT,
        unique_key=f"blind_expire:{attempt_id}:{int(due.timestamp() * 1000)}",
        lock=f"blind_attempt:{attempt_id}",
        run_at=due,
        attempt_id=str(attempt_id),
    )


@job(Lane.BACKGROUND, EXPIRE_ATTEMPT)
async def expire_attempt_job(deps: JobDeps, attempt_id: str) -> None:
    await expire_attempt(deps.database, uuid.UUID(attempt_id), datetime.now(UTC))


async def expire_attempt(database: Database, attempt_id: uuid.UUID, now: datetime) -> None:
    """Void a stale active listen, or schedule its check after the latest heartbeat.

    Locking the Blind row serializes this with heartbeats, client voids and gist
    submission. A retried job is harmless because the attempt and event are idempotent.
    """
    async with database.transaction() as session:
        row = await repository.get(session, attempt_id, lock=True)
        if row is None or row.void_reason is not None or row.listen.complete:
            return
        try:
            attempt = await practice.get_attempt(session, attempt_id)
        except ProblemError:
            return
        if attempt.mode is not Step.BLIND or attempt.status is not AttemptStatus.ACTIVE:
            return
        if now < row.listen.abandonment_deadline():
            await queue_expiry(session, attempt.id, row.listen)
            return

        await repository.save(
            session, attempt.id, row.listen, void_reason=VoidReason.MISSED_HEARTBEAT.value
        )
        ended = await practice.finish_attempt(session, attempt.id, AttemptStatus.VOIDED)
        await publish(session, ended.user_id, LiveEventType.ATTEMPT_VOIDED, ended.id)
        await analytics.record_blind_abandoned(
            session,
            ended.user_id,
            ended.session_id,
            ended.id,
            reason=VoidReason.MISSED_HEARTBEAT.value,
        )
