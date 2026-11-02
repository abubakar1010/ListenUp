"""HTTP routes of the admin module (#100, #105, Architecture 9.2: Admin, ADR 0045, 0098).

Every route takes `CurrentAdmin`: a learner who is not an administrator gets 404.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from listenup.modules.admin import service
from listenup.modules.admin.service import CurrentAdmin
from listenup.modules.admin.usage import UsageOverview
from listenup.platform.clock import server_now
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

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


@router.get("/usage", responses={**NOT_FOUND, 503: {"description": "Reporting unavailable"}})
async def usage_overview(
    admin: CurrentAdmin,
    request: Request,
    response: Response,
    now: Annotated[datetime, Depends(server_now)],
) -> UsageOverview:
    """Content-free daily usage for the last 30 UTC dates and current quota consumption."""
    overview = await service.usage_overview(
        request.app.state.admin_report_database, request.app.state.settings.ai_config, now
    )
    response.headers["Cache-Control"] = "private, no-store"
    return overview


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


class TakedownRequest(BaseModel):
    fingerprint: str = Field(
        max_length=200,
        description=(
            "The taken-down source: `upload:<sha256>`, the SHA-256 in hex of the file the "
            "rights holder identified (`sha256sum`). YouTube links follow with #38"
        ),
    )
    grounds: service.Grounds = Field(
        description="Why, as affected learners are told: copyright, other rights or the law"
    )
    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="The administrator's note on the notice. Never shown to a learner",
    )

    @field_validator("fingerprint")
    @classmethod
    def _source(cls, value: str) -> str:
        stored = service.source_fingerprint(value)
        if stored is None:
            raise ValueError("expected upload:<sha256 in hex>")
        return stored

    @field_validator("reason")
    @classmethod
    def _note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the reason must not be blank")
        return value


class Takedown(BaseModel):
    id: uuid.UUID
    fingerprint: str
    grounds: service.Grounds
    received_at: datetime
    actioned_at: datetime | None = Field(
        description="When every learner's copy was removed; null while the job runs"
    )


@router.post(
    "/takedowns",
    status_code=202,
    response_model=Takedown,
    responses={
        **NOT_FOUND,
        409: {"description": "This source is already taken down (`takedown_exists`)"},
    },
)
async def record_takedown(
    body: TakedownRequest,
    request: Request,
    admin: CurrentAdmin,
    session: DbSession,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Record a takedown (SRS 2.2, #105). A background job removes the file and its
    playback files for every learner who has it, keeps their sessions, marks and cards,
    tells them why, and intake refuses the file afterwards."""

    async def handle() -> tuple[int, Any]:
        recorded = await service.record_takedown(
            session, body.fingerprint, body.grounds, body.reason
        )
        return 202, Takedown.model_validate(recorded, from_attributes=True).model_dump(mode="json")

    answer = await run_once(
        session, admin, idempotency_key, await request_fingerprint(request), handle
    )
    answer.headers["Cache-Control"] = "private, no-store"
    return answer
