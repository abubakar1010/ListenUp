"""HTTP routes of the admin module (#100, Architecture 9.2: Admin, ADR 0034).

Every route takes `CurrentAdmin`: a learner who is not an administrator gets 404.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from listenup.modules.admin import service
from listenup.modules.admin.service import CurrentAdmin
from listenup.platform.database import DbSession

router = APIRouter(prefix="/admin", tags=["admin"])

LaneName = Literal["speech-interactive", "intake", "ai", "background"]


class LaneBacklog(BaseModel):
    lane: LaneName
    waiting: int = Field(description="Jobs due now and not started yet")
    scheduled: int = Field(description="Jobs set to start later, such as a retry's backoff")
    running: int
    oldest_wait_seconds: float | None = Field(
        description="How long the longest-waiting due job has waited; null if none waits"
    )


class FailedJob(BaseModel):
    id: int
    lane: str
    name: str = Field(description="The job's task name, such as content.convert_upload")
    attempts: int
    failed_at: datetime | None


class JobsOverview(BaseModel):
    lanes: list[LaneBacklog] = Field(description="Every lane, highest priority first")
    failed: list[FailedJob] = Field(
        description="Failed jobs not retried yet, newest first (at most 50)"
    )


class RetriedJob(BaseModel):
    job_id: int = Field(description="The id of the new job")


NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"description": "Not an administrator (`not_found`)"}
}


@router.get("/jobs", responses=NOT_FOUND)
async def jobs_overview(
    admin: CurrentAdmin, session: DbSession, response: Response
) -> JobsOverview:
    """Backlog per lane and the failed jobs. Shows no job arguments, so no learner data."""
    overview = await service.jobs_overview(session)
    response.headers["Cache-Control"] = "private, no-store"
    return JobsOverview(
        lanes=[LaneBacklog.model_validate(lane, from_attributes=True) for lane in overview.lanes],
        failed=[FailedJob.model_validate(job, from_attributes=True) for job in overview.failed],
    )


@router.post(
    "/jobs/{job_id}/retry",
    status_code=202,
    responses={
        404: {
            "description": (
                "Not an administrator (`not_found`), or no failed job with this id waits "
                "for a retry (`job_not_found`)"
            )
        },
        409: {"description": "The same work is already queued (`job_already_queued`)"},
    },
)
async def retry_job(job_id: int, admin: CurrentAdmin, session: DbSession) -> RetriedJob:
    """Queue a failed job again, with fresh attempts. A job is retried once; a second
    retry of the same job answers 404 `job_not_found`."""
    return RetriedJob(job_id=await service.retry(session, job_id))
