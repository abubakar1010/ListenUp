"""SQL for data export requests (`ops.data_exports`, migration 0012).

The API's statements run as the API role under row-level security; the jobs' run as
the workers' role, which bypasses it, so every job statement names the learner too.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ExportRow:
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    archive_key: str | None
    archive_bytes: int | None
    file_count: int | None
    error_code: str | None
    requested_at: datetime
    ready_at: datetime | None
    expires_at: datetime | None


_COLUMNS = (
    "id, user_id, status, archive_key, archive_bytes, file_count, error_code, "
    "requested_at, ready_at, expires_at"
)


async def insert_request(
    session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID
) -> ExportRow | None:
    """Record a new request; None when one of the learner's is already pending or building."""
    row = (
        await session.execute(
            text(f"""
            INSERT INTO ops.data_exports (id, user_id) VALUES (:id, :learner)
            ON CONFLICT (user_id) WHERE status IN ('pending', 'building') DO NOTHING
            RETURNING {_COLUMNS}
            """),
            {"id": export_id, "learner": learner},
        )
    ).first()
    return ExportRow(*row) if row else None


async def live_export(session: AsyncSession, learner: uuid.UUID) -> ExportRow | None:
    """The learner's export that is pending or building, if any."""
    row = (
        await session.execute(
            text(f"""
            SELECT {_COLUMNS} FROM ops.data_exports
             WHERE user_id = :learner AND status IN ('pending', 'building')
            """),
            {"learner": learner},
        )
    ).first()
    return ExportRow(*row) if row else None


async def latest(session: AsyncSession, learner: uuid.UUID) -> ExportRow | None:
    row = (
        await session.execute(
            text(f"""
            SELECT {_COLUMNS} FROM ops.data_exports WHERE user_id = :learner
             ORDER BY requested_at DESC, id DESC LIMIT 1
            """),
            {"learner": learner},
        )
    ).first()
    return ExportRow(*row) if row else None


async def get(session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID) -> ExportRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM ops.data_exports WHERE id = :id AND user_id = :learner"),
            {"id": export_id, "learner": learner},
        )
    ).first()
    return ExportRow(*row) if row else None


async def start_building(session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID) -> bool:
    """Mark a pending (or interrupted) build as building; False when there is nothing to build."""
    result = await session.execute(
        text("""
        UPDATE ops.data_exports SET status = 'building'
         WHERE id = :id AND user_id = :learner AND status IN ('pending', 'building')
        RETURNING 1
        """),
        {"id": export_id, "learner": learner},
    )
    return result.first() is not None


async def mark_ready(
    session: AsyncSession,
    export_id: uuid.UUID,
    learner: uuid.UUID,
    *,
    archive_key: str,
    archive_bytes: int,
    file_count: int,
    ready_at: datetime,
    expires_at: datetime,
) -> bool:
    result = await session.execute(
        text("""
        UPDATE ops.data_exports
           SET status = 'ready', archive_key = :archive_key, archive_bytes = :archive_bytes,
               file_count = :file_count, ready_at = :ready_at, expires_at = :expires_at,
               error_code = NULL
         WHERE id = :id AND user_id = :learner AND status = 'building'
        RETURNING 1
        """),
        {
            "id": export_id,
            "learner": learner,
            "archive_key": archive_key,
            "archive_bytes": archive_bytes,
            "file_count": file_count,
            "ready_at": ready_at,
            "expires_at": expires_at,
        },
    )
    return result.first() is not None


async def mark_failed(
    session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID, error_code: str
) -> bool:
    result = await session.execute(
        text("""
        UPDATE ops.data_exports SET status = 'failed', error_code = :error_code
         WHERE id = :id AND user_id = :learner AND status IN ('pending', 'building')
        RETURNING 1
        """),
        {"id": export_id, "learner": learner, "error_code": error_code},
    )
    return result.first() is not None


async def mark_expired(session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID) -> None:
    await session.execute(
        text("""
        UPDATE ops.data_exports SET status = 'expired'
         WHERE id = :id AND user_id = :learner AND status = 'ready'
        """),
        {"id": export_id, "learner": learner},
    )
