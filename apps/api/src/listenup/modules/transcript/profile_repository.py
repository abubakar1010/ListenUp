"""Worker-owned profile cache and durable learner readiness (#76)."""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.identity import service as identity
from listenup.modules.transcript import repository
from listenup.modules.transcript.domain.spans import missing_spans
from listenup.modules.transcript.models import ProfileSubscription, ReferenceProfile
from listenup.platform.events import EventType, publish


async def lock(db: AsyncSession, media: uuid.UUID) -> None:
    # Subscribe and finish use the same short transaction lock: no lost subscriber
    # between the completion scan and commit. Inference never holds a transaction.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"profile-plan:{media}"},
    )


async def find(
    db: AsyncSession, transcript: uuid.UUID, fingerprint: str
) -> ReferenceProfile | None:
    return await db.get(ReferenceProfile, (transcript, fingerprint))


async def ensure(db: AsyncSession, transcript: uuid.UUID, fingerprint: str) -> ReferenceProfile:
    await db.execute(
        insert(ReferenceProfile)
        .values(passage_transcript_id=transcript, fingerprint=fingerprint)
        .on_conflict_do_nothing()
    )
    row = await find(db, transcript, fingerprint)
    assert row is not None
    return row


async def subscribe(
    db: AsyncSession,
    session: uuid.UUID,
    learner: uuid.UUID,
    media: uuid.UUID,
    span: tuple[int, int],
    fingerprint: str,
) -> None:
    statement = insert(ProfileSubscription).values(
        session_id=session,
        user_id=learner,
        media_object_id=media,
        span=Range(*span),
        fingerprint=fingerprint,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["session_id"],
            set_={"fingerprint": fingerprint, "span": Range(*span), "status": "pending"},
            where=ProfileSubscription.fingerprint != fingerprint,
        )
    )


async def settle(db: AsyncSession, media: uuid.UUID) -> None:
    subscriptions = list(
        await db.scalars(
            select(ProfileSubscription)
            .where(ProfileSubscription.media_object_id == media)
            .with_for_update()
        )
    )
    for sub in subscriptions:
        if not await identity.account_is_active(db, sub.user_id):
            continue
        assert sub.span.lower is not None and sub.span.upper is not None
        span = sub.span.lower, sub.span.upper
        rows = await repository.overlapping(db, media, span)
        profiles = [await find(db, row.id, sub.fingerprint) for row in rows]
        state = "pending"
        if any(row is not None and row.status == "failed" for row in profiles):
            state = "failed"
        elif not missing_spans(span, [row.bounds for row in rows]) and all(
            row is not None and row.status == "ready" for row in profiles
        ):
            state = "ready"
        if sub.status != state:
            sub.status = state
            if state in ("ready", "failed"):
                await publish(
                    db,
                    sub.user_id,
                    EventType.PROFILE_READY if state == "ready" else EventType.PROFILE_FAILED,
                    sub.session_id,
                )


async def finish(
    db: AsyncSession, transcript: uuid.UUID, fingerprint: str, values: dict[str, Any]
) -> None:
    row = await find(db, transcript, fingerprint)
    if row is not None:
        for key, value in values.items():
            setattr(row, key, value)
        await db.flush()
