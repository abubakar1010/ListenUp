"""Background jobs of the export module (#92, NFR-SEC-5, ADR 0030).

`export.build_archive` collects every module's rows and files for one learner and
writes a ZIP archive to `users/<user id>/exports/<export id>.zip`; `export.expire_archive`
deletes it once its keep period ends. Both run on the background lane.
"""

import asyncio
import json
import logging
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.export import repository
from listenup.modules.export.collect import collect
from listenup.modules.export.domain import archive
from listenup.modules.identity import service as identity
from listenup.platform.config import get_settings
from listenup.platform.database import Database, set_learner
from listenup.platform.events import EventType, publish
from listenup.platform.export import ExportPart
from listenup.platform.jobs import JobDeps, Lane, enqueue, job
from listenup.platform.storage import Storage, get_storage

logger = logging.getLogger(__name__)

BUILD_ARCHIVE = "export.build_archive"
EXPIRE_ARCHIVE = "export.expire_archive"
BUILD_ATTEMPTS = 3
# Copying up to the 2 GB upload cap (D5) out of storage and back takes minutes.
BUILD_TIMEOUT = timedelta(minutes=45)


async def queue_build(session: AsyncSession, export_id: uuid.UUID, learner: uuid.UUID) -> None:
    """Queue the build of a new export request, in the transaction that records it."""
    await enqueue(
        session,
        BUILD_ARCHIVE,
        unique_key=f"export_build:{export_id}",
        lock=f"export:{learner}",
        export_id=str(export_id),
        user_id=str(learner),
    )


async def _give_up_build(deps: JobDeps, export_id: str, user_id: str) -> None:
    """The last attempt failed or timed out: mark the request failed and say so, so it
    no longer blocks a new export."""
    export = uuid.UUID(export_id)
    learner = uuid.UUID(user_id)
    async with deps.database.transaction(learner) as session:
        if await repository.mark_failed(session, export, learner, "export_failed"):
            await publish(session, learner, EventType.EXPORT_READY, export)


@job(
    Lane.BACKGROUND,
    BUILD_ARCHIVE,
    timeout=BUILD_TIMEOUT,
    max_attempts=BUILD_ATTEMPTS,
    on_give_up=_give_up_build,
)
async def build_archive(deps: JobDeps, export_id: str, user_id: str) -> None:
    """Build the learner's export archive and tell the browser it is ready.

    1. Mark the request 'building' (a repeated run after a crash builds again), or
       'failed' when the learner has deleted the account since asking.
    2. Read every module's rows in one read-only snapshot, so the tables agree.
    3. Copy the learner's files from storage into a ZIP in scratch space, then write
       data.json with every row and the list of files.
    4. Store the archive under the learner's prefix; mark it 'ready' with its expiry,
       publish `export.ready` and queue its deletion, all in one transaction.

    When the last attempt fails, the request is marked 'failed' and announced the same
    way, so the learner can ask again.
    """
    await _build(deps.database, get_storage(), uuid.UUID(export_id), uuid.UUID(user_id))


async def _build(
    database: Database, storage: Storage, export: uuid.UUID, learner: uuid.UUID
) -> None:
    async with database.transaction(learner) as session:
        if not await identity.account_is_active(session, learner):
            # Deleted after asking (ADR 0029): no copy of the data for a disabled
            # account. A learner who restores it can ask again.
            await repository.mark_failed(session, export, learner, "account_deleted")
            logger.info("export build skipped: account deleted", extra={"export": str(export)})
            return
        if not await repository.start_building(session, export, learner):
            logger.info("export build skipped: nothing to build", extra={"export": str(export)})
            return

    parts, exported_at = await _snapshot(database, learner)
    settings = get_settings()
    key = archive.archive_key(learner, export)
    with tempfile.TemporaryDirectory(
        prefix="listenup-export-", dir=settings.media_scratch_dir
    ) as scratch:
        zip_path = Path(scratch) / "export.zip"
        file_count = await _write_archive(
            storage, zip_path, Path(scratch), parts, learner, export, exported_at
        )
        size = zip_path.stat().st_size
        await storage.put_file(key, zip_path, "application/zip")

    ready_at = datetime.now(UTC)
    expires_at = archive.expires_at(ready_at, settings.export_keep_days)
    async with database.transaction(learner) as session:
        # The account may have been deleted while the archive was built; the check holds
        # the row, so a deletion cannot slip in before this transaction commits.
        if await identity.hold_active_account(session, learner):
            stored = await repository.mark_ready(
                session,
                export,
                learner,
                archive_key=key,
                archive_bytes=size,
                file_count=file_count,
                ready_at=ready_at,
                expires_at=expires_at,
            )
        else:
            stored = False
            await repository.mark_failed(session, export, learner, "account_deleted")
        if stored:
            await publish(session, learner, EventType.EXPORT_READY, export)
            await queue_expiry(session, export, learner, expires_at)
    if not stored:
        # The account was deleted while the archive was built: keep no copy of its data.
        await storage.delete(key)
        return
    logger.info("export ready", extra={"export": str(export), "bytes": size, "files": file_count})


async def _snapshot(database: Database, learner: uuid.UUID) -> tuple[list[ExportPart], datetime]:
    """Every module's part, read in one repeatable-read snapshot."""
    async with database.transaction() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await set_learner(session, learner)
        exported_at = (await session.execute(text("SELECT now()"))).scalar_one()
        return await collect(session, learner), exported_at


async def _write_archive(
    storage: Storage,
    zip_path: Path,
    scratch: Path,
    parts: list[ExportPart],
    learner: uuid.UUID,
    export: uuid.UUID,
    exported_at: datetime,
) -> int:
    """Write the ZIP: the learner's files first, then data.json. Returns the file count."""
    entries: list[archive.FileEntry] = []
    missing: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", allowZip64=True) as zf:
        for part in parts:
            for item in part.files:
                if item.path in seen:
                    continue
                if not archive.file_allowed(item.key, item.path, learner):
                    logger.error(
                        "export skipped a file outside the learner's prefix",
                        extra={"export": str(export), "path": item.path},
                    )
                    continue
                seen.add(item.path)
                local = scratch / "file"
                downloaded = await storage.download(item.key, local)
                if downloaded is None:
                    missing.append(item.path)
                    continue
                # Media is compressed already: store it as it is, in a worker thread.
                await asyncio.to_thread(
                    zf.write, local, item.path, compress_type=zipfile.ZIP_STORED
                )
                local.unlink()
                entries.append(archive.FileEntry(item.path, downloaded.size, downloaded.sha256))

        tables = [
            archive.TableData(table.name, table.rows, table.omitted)
            for part in parts
            for table in part.tables
        ]
        document = archive.document(learner, export, exported_at, tables, entries, missing)
        data = json.dumps(document, ensure_ascii=False, indent=1).encode()
        zf.writestr(archive.DATA_FILE, data, compress_type=zipfile.ZIP_DEFLATED)
    return len(entries)


async def queue_expiry(
    session: AsyncSession, export: uuid.UUID, learner: uuid.UUID, expires_at: datetime
) -> None:
    await enqueue(
        session,
        EXPIRE_ARCHIVE,
        unique_key=f"export_expire:{export}",
        run_at=expires_at,
        export_id=str(export),
        user_id=str(learner),
    )


@job(Lane.BACKGROUND, EXPIRE_ARCHIVE)
async def expire_archive(deps: JobDeps, export_id: str, user_id: str) -> None:
    """Delete an archive whose keep period has ended and mark its request 'expired'.

    Safe to repeat: the archive is deleted before the row changes, and deleting a
    missing object is not an error.
    """
    export = uuid.UUID(export_id)
    learner = uuid.UUID(user_id)
    async with deps.database.transaction(learner) as session:
        row = await repository.get(session, export, learner)
    if row is None or row.archive_key is None or row.status not in ("ready", "expired"):
        return
    assert row.expires_at is not None  # a ready export always has its expiry
    now = datetime.now(UTC)
    if row.expires_at > now:
        async with deps.database.transaction(learner) as session:
            await queue_expiry(session, export, learner, row.expires_at)
        return
    await get_storage().delete(row.archive_key)
    async with deps.database.transaction(learner) as session:
        await repository.mark_expired(session, export, learner)
    logger.info("export archive expired", extra={"export": str(export)})
