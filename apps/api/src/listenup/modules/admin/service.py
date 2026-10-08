"""Administration: the job view and retries (#100, SRS 2.2, Architecture 9.2: Admin).

The public face of the admin module. `CurrentAdmin` lets in only administrators
(ADR 0034); anyone else signed in gets the same 404 as a path that does not exist, so
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

from listenup.modules.admin import repository
from listenup.modules.admin.domain.roles import is_admin
from listenup.modules.identity import service as identity
from listenup.modules.identity.service import CurrentLearner
from listenup.platform import jobs
from listenup.platform.database import DbSession
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import Lane

__all__ = ["CurrentAdmin", "FailedJob", "JobsOverview", "LaneBacklog", "jobs_overview", "retry"]

FAILED_SHOWN = 50


def _not_found() -> ProblemError:
    # The same answer as a route that does not exist (platform/errors.py).
    return ProblemError(404, "not_found", "Not Found")


async def current_admin(request: Request, learner: CurrentLearner, session: DbSession) -> uuid.UUID:
    profile = await identity.get_profile(session, learner)
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
