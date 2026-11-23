"""Administration: the job view, retries and takedowns (#100, #105, SRS 2.2,
Architecture 9.2: Admin).

The public face of the admin module. `CurrentAdmin` lets in only administrators
(ADR 0045); anyone else signed in gets the same 404 as a path that does not exist, so
a learner cannot tell that admin routes are there. Admin answers carry counts, job
ids, lanes and job names only, never job arguments, so no learner id, media or text
reaches them.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.admin import jobs as admin_jobs
from listenup.modules.admin import repository
from listenup.modules.admin.domain.roles import is_admin
from listenup.modules.admin.usage import usage_overview
from listenup.modules.content import service as content
from listenup.modules.identity import service as identity
from listenup.modules.identity.service import CurrentLearner
from listenup.platform import jobs
from listenup.platform.database import DbSession
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7
from listenup.platform.jobs import Lane

__all__ = [
    "CurrentAdmin",
    "FailedJob",
    "Grounds",
    "JobsOverview",
    "LaneBacklog",
    "RecordedTakedown",
    "jobs_overview",
    "record_takedown",
    "retry",
    "source_fingerprint",
    "usage_overview",
]

Grounds = content.RemovalGrounds
source_fingerprint = content.source_fingerprint

FAILED_SHOWN = 50


def _not_found() -> ProblemError:
    # The same answer as a route that does not exist (platform/errors.py).
    return ProblemError(404, "not_found", "Not Found")


async def current_admin(request: Request, learner: CurrentLearner, session: DbSession) -> uuid.UUID:
    profile = await identity.get_accounts(request).profile(session, learner)
    admins: tuple[str, ...] = request.app.state.settings.admin_emails
    if not is_admin(str(profile["email"]), bool(profile["email_verified"]), admins):
        raise _not_found()
    return learner


CurrentAdmin = Annotated[uuid.UUID, Depends(current_admin)]


@dataclass(frozen=True)
class LaneBacklog:
    lane: Lane
    waiting: int
    scheduled: int
    running: int
    oldest_wait_seconds: float | None


@dataclass(frozen=True)
class FailedJob:
    id: int
    lane: str
    name: str
    attempts: int
    failed_at: datetime | None


@dataclass(frozen=True)
class JobsOverview:
    lanes: list[LaneBacklog]
    failed: list[FailedJob]


async def jobs_overview(session: AsyncSession) -> JobsOverview:
    """Backlog of every lane, in priority order, and the newest failed jobs."""
    backlog = await repository.lane_backlog(session)
    lanes = []
    for lane in Lane:
        row = backlog.get(lane.value)
        lanes.append(
            LaneBacklog(lane, row.waiting, row.scheduled, row.running, row.oldest_wait_seconds)
            if row
            else LaneBacklog(lane, 0, 0, 0, None)
        )
    failed = [
        FailedJob(row["id"], row["lane"], row["name"], row["attempts"], row["failed_at"])
        for row in await jobs.failed_jobs(session, FAILED_SHOWN)
    ]
    return JobsOverview(lanes, failed)


async def retry(session: AsyncSession, job_id: int) -> int:
    """Queue failed job `job_id` again; returns the new job's id."""
    try:
        new_id = await jobs.retry_failed_job(session, job_id)
    except jobs.JobNotRetryable:
        raise ProblemError(
            404,
            "job_not_found",
            "No failed job with this id is waiting for a retry. It may have been retried "
            "already; reload the list.",
        ) from None
    if new_id is None:
        raise ProblemError(
            409,
            "job_already_queued",
            "The same work is already waiting in the queue, so this job was not queued again.",
        )
    return new_id


@dataclass(frozen=True)
class RecordedTakedown:
    id: uuid.UUID
    fingerprint: str
    grounds: str
    received_at: datetime
    actioned_at: datetime | None


async def record_takedown(
    session: AsyncSession, fingerprint: str, grounds: str, reason: str
) -> RecordedTakedown:
    """Record a takedown of a source (#105, ADR 0098) and queue its removal for every
    learner, in the same transaction. A source is taken down once: a second request
    answers 409 `takedown_exists` with the first one's id."""
    row = await repository.insert_takedown(session, uuid7(), fingerprint, grounds, reason)
    if row is None:
        existing = await repository.takedown_by_fingerprint(session, fingerprint)
        raise ProblemError(
            409,
            "takedown_exists",
            "This file is already taken down; its removal is recorded once.",
            takedown_id=str(existing.id) if existing else None,
        )
    await admin_jobs.queue_takedown(session, row.id)
    return RecordedTakedown(row.id, row.fingerprint, row.grounds, row.received_at, row.actioned_at)
