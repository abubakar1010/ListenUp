"""HTTP routes of the export module (Architecture 9.2: Account; #92, NFR-SEC-5)."""

import dataclasses
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from listenup.modules.export import service
from listenup.modules.export.service import ExportsDep
from listenup.modules.identity.service import CurrentLearner
from listenup.platform.database import DbSession
from listenup.platform.idempotency import IdempotencyKeyHeader, request_fingerprint, run_once

router = APIRouter(tags=["export"])


class DataExport(BaseModel):
    id: uuid.UUID
    status: Literal["pending", "building", "ready", "failed", "expired"]
    requested_at: datetime
    ready_at: datetime | None
    expires_at: datetime | None = Field(description="When the archive is deleted")
    archive_bytes: int | None
    file_count: int | None = Field(description="Media files in the archive besides data.json")
    download_url: str | None = Field(
        description=(
            "API path that redirects to a short-lived link of the archive; "
            "null unless the export is ready"
        )
    )


class LatestExport(BaseModel):
    export: DataExport | None


def _out(export: service.DataExport) -> DataExport:
    fields = dataclasses.asdict(export)
    downloadable = fields.pop("downloadable")
    return DataExport(
        **fields,
        download_url=f"/api/v1/me/exports/{export.id}/download" if downloadable else None,
    )


@router.post(
    "/me/exports",
    status_code=202,
    response_model=DataExport,
    responses={
        409: {"description": "An export is already being prepared (`export_in_progress`)"},
        429: {"description": "Too many exports today (`rate_limited`, with `retry_after`)"},
    },
)
async def request_export(
    request: Request,
    learner: CurrentLearner,
    session: DbSession,
    exports: ExportsDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Start a copy of all the learner's data: a ZIP with data.json and their uploaded
    media. It is built in the background; `export.ready` tells the browser when it is
    ready or has failed. YouTube media files are not included (D10)."""

    async def start() -> tuple[int, Any]:
        started = await exports.request(session, learner)
        return 202, _out(started).model_dump(mode="json")

    return await run_once(
        session, learner, idempotency_key, await request_fingerprint(request), start
    )


@router.get("/me/exports/latest")
async def latest_export(
    learner: CurrentLearner, session: DbSession, exports: ExportsDep, response: Response
) -> LatestExport:
    """The learner's most recent export and its status; `export` is null if none."""
    found = await exports.latest(session, learner)
    response.headers["Cache-Control"] = "private, no-cache"
    return LatestExport(export=_out(found) if found else None)


@router.get(
    "/me/exports/{export_id}/download",
    response_class=RedirectResponse,
    status_code=307,
    responses={
        307: {"description": "Redirect to a short-lived signed link of the archive"},
        404: {"description": "Not an export of yours (`export_not_found`)"},
        409: {"description": "Not ready (`export_not_ready`)"},
        410: {"description": "Expired and deleted (`export_expired`)"},
    },
)
async def download_export(
    export_id: uuid.UUID, learner: CurrentLearner, session: DbSession, exports: ExportsDep
) -> RedirectResponse:
    """Download the archive. Needs the owner's session; the link it redirects to works
    for a short time only."""
    url = await exports.download_url(session, learner, export_id)
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, no-store"})
