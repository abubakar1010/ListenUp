"""Data export: a learner's copy of their data (#92, NFR-SEC-5, ADR 0030).

The public face of the export module (Architecture 9.2: Account).

1. `Exports.request` records a request in `ops.data_exports` and queues the build job
   in the same transaction. One export is built at a time per learner
   (409 `export_in_progress`), and a learner may ask `export_daily_limit` times per
   UTC day (429 `rate_limited`).
2. The job (`jobs.build_archive`) writes the archive under `users/<user id>/exports/`
   and publishes `export.ready`.
3. `Exports.download_url` checks that the export is the caller's, ready and not
   expired, and signs a short-lived storage URL for it; the API answers with a
   redirect, so no storage URL is ever kept in a cached response.
4. The archive is deleted when its keep period ends (`jobs.expire_archive`).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.export import jobs, repository
from listenup.modules.export.domain import archive
from listenup.modules.export.repository import ExportRow
from listenup.platform.config import Settings
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7
from listenup.platform.rate_limit import Limit, RateLimiter, user_key
from listenup.platform.storage import Storage

__all__ = ["DataExport", "Exports", "ExportsDep", "build_exports"]


@dataclass(frozen=True)
class DataExport:
    id: uuid.UUID
    status: str  # pending, building, ready, failed or expired
    requested_at: datetime
    ready_at: datetime | None
    expires_at: datetime | None
    archive_bytes: int | None
    file_count: int | None
    downloadable: bool


def _view(row: ExportRow, now: datetime) -> DataExport:
    # A ready archive past its expiry is expired, even before the job deletes it.
    expired = row.status == "ready" and row.expires_at is not None and row.expires_at <= now
    status = "expired" if expired else row.status
    return DataExport(
        id=row.id,
        status=status,
        requested_at=row.requested_at,
        ready_at=row.ready_at,
        expires_at=row.expires_at,
        archive_bytes=row.archive_bytes,
        file_count=row.file_count,
        downloadable=status == "ready",
    )


def _not_found() -> ProblemError:
    return ProblemError(404, "export_not_found", "There is no such export of your data.")


class Exports:
    def __init__(self, settings: Settings, storage: Storage, limiter: RateLimiter) -> None:
        self.settings = settings
        self.storage = storage
        self.limiter = limiter
        self.daily = Limit("export", settings.export_daily_limit, timedelta(days=1))

    async def request(self, session: AsyncSession, learner: uuid.UUID) -> DataExport:
        """Start a new export of the learner's data."""
        live = await repository.live_export(session, learner)
        if live is not None:
            raise self._in_progress(live.id)
        await self.limiter.enforce(self.daily, user_key(self.daily, learner))
        row = await repository.insert_request(session, uuid7(), learner)
        if row is None:  # a second request got in between
            live = await repository.live_export(session, learner)
            raise self._in_progress(live.id if live else None)
        await jobs.queue_build(session, row.id, learner)
        return _view(row, datetime.now(UTC))

    @staticmethod
    def _in_progress(export_id: uuid.UUID | None) -> ProblemError:
        return ProblemError(
            409,
            "export_in_progress",
            "An export of your data is already being prepared. We'll show it here when it "
            "is ready.",
            export_id=str(export_id) if export_id else None,
        )

    async def latest(self, session: AsyncSession, learner: uuid.UUID) -> DataExport | None:
        row = await repository.latest(session, learner)
        return _view(row, datetime.now(UTC)) if row else None

    async def download_url(
        self, session: AsyncSession, learner: uuid.UUID, export_id: uuid.UUID
    ) -> str:
        """A signed URL of the archive, valid for `export_link_seconds`.

        Refused with 404 `export_not_found` for anyone but the owner, 409
        `export_not_ready` while it is built (or when it failed), and 410
        `export_expired` once its keep period has ended.
        """
        row = await repository.get(session, export_id, learner)
        if row is None:
            raise _not_found()
        view = _view(row, datetime.now(UTC))
        if view.status == "expired":
            raise ProblemError(
                410,
                "export_expired",
                "This export has expired and its file was deleted. Ask for a new export.",
            )
        if view.status != "ready" or row.archive_key is None or row.ready_at is None:
            raise ProblemError(
                409,
                "export_not_ready",
                "This export is not ready to download.",
                export_status=view.status,
            )
        signed = self.storage.signed_download(
            row.archive_key,
            download_name=archive.download_name(row.ready_at),
            ttl_seconds=self.settings.export_link_seconds,
        )
        return signed.url


def get_exports(request: Request) -> Exports:
    exports: Exports = request.app.state.exports
    return exports


def build_exports(settings: Settings, storage: Storage, limiter: RateLimiter) -> Exports:
    return Exports(settings, storage, limiter)


ExportsDep = Annotated[Exports, Depends(get_exports)]
