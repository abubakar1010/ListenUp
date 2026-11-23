"""Idempotent snippet generation and retryable object cleanup (FR-CA-2)."""

import tempfile
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.cards import audio, repository, writes
from listenup.modules.content import service as content
from listenup.modules.identity import service as identity
from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.config import get_settings
from listenup.platform.errors import ProblemError
from listenup.platform.events import EventType, publish
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job
from listenup.platform.storage import get_storage

GENERATE = "cards.generate_snippet"
CLEANUP = "cards.cleanup_snippets"

identity.on_account_purge(repository.require_no_audio_writes)


def snippet_key(user_id: uuid.UUID, card_id: uuid.UUID) -> str:
    return f"users/{user_id}/cards/{card_id}/snippet.m4a"


async def give_up(
    deps: JobDeps, *, card_id: str, user_id: str, generation_id: str | None = None
) -> None:
    learner, card = uuid.UUID(user_id), uuid.UUID(card_id)
    async with deps.database.transaction(learner) as db:
        row = await repository.audio_row(db, card, learner, lock=True)
        generation = uuid.UUID(generation_id) if generation_id else None
        if row and row.audio_status == "pending" and row.audio_generation == generation:
            await db.execute(
                text("UPDATE practice.cards SET audio_status='failed' WHERE id=:id"), {"id": card}
            )
            await publish(db, learner, EventType.CARD_AUDIO_UPDATED, row.session_id)


async def _clip_removed(db: AsyncSession, learner: uuid.UUID, content_id: uuid.UUID) -> bool:
    return (await content.get_content(db, learner, content_id)).status == "removed"


async def _withdraw(
    db: AsyncSession,
    learner: uuid.UUID,
    card: uuid.UUID,
    generation: uuid.UUID | None,
    session_id: uuid.UUID,
) -> None:
    changed = await db.execute(
        text(
            "UPDATE practice.cards SET audio_status='unavailable', snippet_key=NULL, "
            "audio_generation=NULL WHERE id=:id AND audio_status='pending' "
            "AND audio_generation IS NOT DISTINCT FROM :generation RETURNING id"
        ),
        {"id": card, "generation": generation},
    )
    if changed.first() is not None:
        await publish(db, learner, EventType.CARD_AUDIO_UPDATED, session_id)


@job(Lane.INTAKE, GENERATE, on_give_up=give_up)
async def generate_snippet(
    deps: JobDeps, *, card_id: str, user_id: str, generation_id: str | None = None
) -> None:
    try:
        await _generate_snippet(deps, card_id=card_id, user_id=user_id, generation_id=generation_id)
    except PermanentError:
        # Like transcription, settle in the handler before the sandbox returns
        # exit 65. The shared runner leaves permanent refusals to each handler.
        await give_up(deps, card_id=card_id, user_id=user_id, generation_id=generation_id)
        raise


async def _generate_snippet(
    deps: JobDeps, *, card_id: str, user_id: str, generation_id: str | None = None
) -> None:
    learner, card = uuid.UUID(user_id), uuid.UUID(card_id)
    generation = uuid.UUID(generation_id) if generation_id else None
    async with deps.database.transaction(learner) as db:
        row = await repository.audio_row(db, card, learner)
        if not row or row.audio_status != "pending" or row.audio_generation != generation:
            return
        if not await identity.account_is_active(db, learner):
            raise PermanentError("The account is no longer active.")
        try:
            source = await content.transcription_source(db, learner, row.content_id)
        except ProblemError as error:
            if error.code not in ("content_not_ready", "content_not_found"):
                raise
            if error.code == "content_not_ready" and await _clip_removed(
                db, learner, row.content_id
            ):
                # A takedown removed the clip (#105, ADR 0098): no snippet can ever be
                # cut, so the audio is unavailable, like the cards the takedown found.
                await _withdraw(db, learner, card, generation, row.session_id)
                return
            raise PermanentError("Source playback is no longer available.") from error
        span = row.snippet_span
    if span is None:
        raise PermanentError("Card has no saved snippet span.")
    storage = get_storage()
    scratch = get_settings().media_scratch_dir
    if scratch is not None:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="card-", dir=scratch) as directory:
        original, target = Path(directory) / "source.mp4", Path(directory) / "snippet.m4a"
        if await storage.download(source.playback_key, original) is None:
            raise PermanentError("Source playback has expired.")
        try:
            await audio.cut(original, target, span.lower, span.upper)
        except ValueError as error:
            raise PermanentError(str(error)) from error
        async with writes.registered_write(deps.database, learner, card, generation) as db:
            # Deletion waits for this lock until storage and readiness are settled.
            # If deletion won during encoding, never create an orphan object.
            row = await repository.audio_row(db, card, learner, lock=True)
            if not row or row.audio_status != "pending" or row.audio_generation != generation:
                return
            if not await identity.account_is_active(db, learner):
                raise PermanentError("The account is no longer active.")
            key = snippet_key(learner, card)
            await finish_on_cancel(storage.put_file(key, target, "audio/mp4"))
            await db.execute(
                text(
                    "UPDATE practice.cards SET snippet_key=:key, audio_status='ready' WHERE id=:id"
                ),
                {"key": key, "id": card},
            )
            await publish(db, learner, EventType.CARD_AUDIO_UPDATED, row.session_id)


@job(Lane.BACKGROUND, CLEANUP, schedule="* * * * *")
async def cleanup_snippets(deps: JobDeps, *, timestamp: int | None = None) -> None:
    # A durable tombstone is removed only after storage confirms deletion. Cascades
    # use the same trigger as DELETE /cards; the schedule recovers unqueued cleanup.
    async with deps.database.transaction() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT card_id,user_id FROM practice.card_snippet_cleanup c "
                    "WHERE NOT EXISTS (SELECT 1 FROM practice.card_snippet_writes w "
                    "WHERE w.card_id=c.card_id) "
                    "ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED"
                )
            )
        ).all()
        for row in rows:
            await get_storage().delete(snippet_key(row.user_id, row.card_id))
            await db.execute(
                text("DELETE FROM practice.card_snippet_cleanup WHERE card_id=:id"),
                {"id": row.card_id},
            )
