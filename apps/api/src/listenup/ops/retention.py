"""Scheduled retention sweeps (#93; Database Design 10.3, FR-SH-17, NFR-SEC-4).

Each sweep is a background job that works in batches of `BATCH` rows chosen with
`FOR UPDATE SKIP LOCKED`, one transaction per batch: it never holds a long lock, skips
rows normal traffic is using, and a second run (or a concurrent one) finds nothing
left to do. Handlers return how many rows or files they removed.

AI call log partitions are created ahead and dropped after 90 days by `ai.maintain`
(#64), which runs every five minutes.

Not here, by the owner's exception E1 on #93: the YouTube sweeps (expired playback
files, unreferenced YouTube media), which wait for #38.
"""

import asyncio
import logging
import shutil
import time
from pathlib import Path

from sqlalchemy import text

from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, job
from listenup.platform.storage import get_storage

logger = logging.getLogger(__name__)

BATCH = 1000

# Daily sweeps run in the quiet hours (UTC); minutes are spread so they do not start
# together.
SHADOW_SCHEDULE = "17 3 * * *"
SESSIONS_SCHEDULE = "23 3 * * *"
TOKENS_SCHEDULE = "29 3 * * *"
IDEMPOTENCY_SCHEDULE = "35 * * * *"
RATE_SCHEDULE = "41 * * * *"
SCRATCH_SCHEDULE = "*/15 * * * *"

# Every directory or file the worker jobs create in LISTENUP_MEDIA_SCRATCH_DIR. Only
# these are swept, so a directory shared with other programs is left alone.
SCRATCH_PREFIXES = (
    "transcript-",
    "profile-",
    "listenup-export-",
    "listenup-convert-",
    "media-job-",
)


async def _delete_in_batches(deps: JobDeps, table: str, condition: str) -> int:
    """Delete rows of `table` matching `condition`, `BATCH` rows per transaction."""
    total = 0
    while True:
        async with deps.database.transaction() as session:
            result = await session.execute(
                text(
                    f"DELETE FROM {table} WHERE ctid IN "
                    f"(SELECT ctid FROM {table} WHERE {condition} "
                    "LIMIT :batch FOR UPDATE SKIP LOCKED)"
                ),
                {"batch": BATCH},
            )
        removed = int(getattr(result, "rowcount", 0) or 0)
        total += removed
        if removed < BATCH:
            return total


@job(Lane.BACKGROUND, "ops.sweep_shadow_recordings", schedule=SHADOW_SCHEDULE)
async def sweep_shadow_recordings(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove Shadow recordings older than the retention period (FR-SH-17, D7).

    The file goes first, then the round's recording columns are cleared; a crash in
    between leaves a key whose file is gone, and the next sweep deletes again (deleting
    a missing file is not an error). The round keeps `recorded_at`, so its scores and
    word labels stay visible. Returns how many recordings it removed.
    """
    days = get_settings().shadow_recording_retention_days
    storage = get_storage()
    total = 0
    while True:
        async with deps.database.transaction() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, recording_key FROM practice.shadow_rounds "
                        "WHERE recording_key IS NOT NULL "
                        "AND recorded_at < now() - make_interval(days => :days) "
                        "ORDER BY recorded_at LIMIT :batch FOR UPDATE SKIP LOCKED"
                    ),
                    {"days": days, "batch": BATCH},
                )
            ).all()
            for _, key in rows:
                await storage.delete(key)
            if rows:
                await session.execute(
                    text(
                        "UPDATE practice.shadow_rounds SET recording_key = NULL, "
                        "recording_mime = NULL, recording_bytes = NULL, uploaded_at = NULL "
                        "WHERE id = ANY(:ids)"
                    ),
                    {"ids": [row[0] for row in rows]},
                )
        total += len(rows)
        if len(rows) < BATCH:
            break
    if total:
        logger.info("shadow recordings expired", extra={"count": total})
    return total


@job(Lane.BACKGROUND, "ops.sweep_login_sessions", schedule=SESSIONS_SCHEDULE)
async def sweep_login_sessions(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove login sessions past their expiry (`auth_sessions_expires_idx`)."""
    return await _delete_in_batches(deps, "identity.auth_sessions", "expires_at < now()")


@job(Lane.BACKGROUND, "ops.sweep_one_time_tokens", schedule=TOKENS_SCHEDULE)
async def sweep_one_time_tokens(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove one-time tokens seven days after they were used or expired."""
    return await _delete_in_batches(
        deps,
        "identity.one_time_tokens",
        "coalesce(used_at, expires_at) < now() - interval '7 days' "
        "OR expires_at < now() - interval '7 days'",
    )


@job(Lane.BACKGROUND, "ops.sweep_idempotency_keys", schedule=IDEMPOTENCY_SCHEDULE)
async def sweep_idempotency_keys(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove idempotency keys after 24 hours (`idempotency_keys_age_idx`)."""
    return await _delete_in_batches(
        deps, "ops.idempotency_keys", "created_at < now() - interval '24 hours'"
    )


@job(Lane.BACKGROUND, "ops.sweep_rate_counters", schedule=RATE_SCHEDULE)
async def sweep_rate_counters(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove rate-limit windows older than a day (`rate_counters_window_idx`)."""
    return await _delete_in_batches(
        deps, "ops.rate_counters", "window_start < now() - interval '1 day'"
    )


def _sweep_scratch(root: Path, max_age_seconds: int) -> int:
    """Remove our entries under `root` that nothing wrote to for `max_age_seconds`."""
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in root.iterdir():
        if not entry.name.startswith(SCRATCH_PREFIXES):
            continue
        try:
            newest = entry.stat().st_mtime
            if entry.is_dir() and not entry.is_symlink():
                newest = max([newest, *(p.stat().st_mtime for p in entry.rglob("*"))])
            if newest >= cutoff:
                continue  # a job may still be using it
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
        except FileNotFoundError:
            continue  # the owning job cleaned up meanwhile
    return removed


@job(Lane.INTAKE, "ops.sweep_scratch_files", schedule=SCRATCH_SCHEDULE)
async def sweep_scratch_files(deps: JobDeps, timestamp: int | None = None) -> int:
    """Remove worker scratch files left behind for over an hour (crashed or killed jobs).

    Runs on the intake lane so it executes in the media pool, where the scratch
    directory is. Without `LISTENUP_MEDIA_SCRATCH_DIR` it does nothing: the system's
    temporary directory is shared with other programs.
    """
    settings = get_settings()
    if settings.media_scratch_dir is None:
        return 0
    root = Path(settings.media_scratch_dir)
    if not root.is_dir():
        return 0
    removed = await asyncio.to_thread(_sweep_scratch, root, settings.scratch_max_age_seconds)
    if removed:
        logger.info("scratch files removed", extra={"count": removed})
    return removed
