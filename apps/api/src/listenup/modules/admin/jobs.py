"""Carrying out a takedown for every learner (#105, SRS 2.2, ADR 0098).

The order follows content deletion (ADR 0085): first a barrier that makes every copy
unavailable and tells its learners, committed before anything else; then a wait for
registered conversion and snippet writers; then storage, outside any transaction; then
the record. Rows are kept, so the learners' sessions, marks and cards stay. A repeated
run deletes again (deleting a missing object is not an error) and reports the same.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.admin import repository
from listenup.modules.cards import service as cards
from listenup.modules.content import service as content
from listenup.platform.jobs import JobDeps, Lane, enqueue, job
from listenup.platform.storage import get_storage

APPLY_TAKEDOWN = "admin.apply_takedown"


async def queue_takedown(db: AsyncSession, takedown_id: uuid.UUID) -> None:
    await enqueue(
        db,
        APPLY_TAKEDOWN,
        unique_key=f"takedown:{takedown_id}",
        lock=f"takedown:{takedown_id}",
        takedown_id=str(takedown_id),
    )


@job(Lane.BACKGROUND, APPLY_TAKEDOWN)
async def apply_takedown(deps: JobDeps, takedown_id: str) -> dict[str, int] | None:
    target = uuid.UUID(takedown_id)
    async with deps.database.transaction() as db:
        record = await repository.takedown(db, target)
        if record is None:
            return None
        media = await content.remove_taken_down_media(db, target, record.fingerprint)
        await cards.withdraw_media_audio(db, media)
    # The barrier is committed: nothing plays or gets a new file from here on.
    async with deps.database.transaction() as db:
        files = await content.taken_down_files(db, target)
        card_prefixes = await cards.media_audio_prefixes(db, media)
    storage = get_storage()
    removed = 0
    for found in files:
        for prefix in found.prefixes:
            removed += await storage.delete_prefix(prefix)
        for key in found.keys:
            await storage.delete(key)
    for prefix in card_prefixes:
        removed += await storage.delete_prefix(prefix)
    async with deps.database.transaction() as db:
        return await repository.finish_takedown(
            db, target, len(files), len({found.learner for found in files}), removed
        )


@job(Lane.BACKGROUND, "admin.reconcile_takedowns", schedule="*/10 * * * *")
async def reconcile_takedowns(deps: JobDeps, timestamp: int | None = None) -> None:
    """Queue again every takedown not carried out yet, such as one whose job gave up."""
    async with deps.database.transaction() as db:
        for target in await repository.unactioned_takedowns(db):
            await queue_takedown(db, target)
