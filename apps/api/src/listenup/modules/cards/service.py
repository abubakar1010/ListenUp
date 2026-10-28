"""Cards public boundary: FR-CA-1..3, two live cards per session (D14)."""

import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.cards import jobs, repository, schemas
from listenup.modules.cards.domain import cursor as cursors
from listenup.modules.cards.domain.snippet import snippet_window
from listenup.modules.cards.domain.suggestions import Candidate, normalize, rank
from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.review import service as review
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportFile, ExportPart, learner_rows
from listenup.platform.ids import uuid7
from listenup.platform.jobs import enqueue
from listenup.platform.storage import Storage


async def create(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    new: schemas.NewCard,
    worker_database: Database,
) -> schemas.Card:
    await repository.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.CARD)
    marks = await review.list_marks(db, session_id)
    mark = next((mark for mark in marks if mark.id == new.mark_id), None)
    if mark is None:
        raise ProblemError(404, "mark_not_found", "There is no such mark in this session.")
    await content.retain_content(db, learner, session.content_id)
    item = await content.get_content(db, learner, session.content_id)
    transcript = await review.read_transcript(db, worker_database, learner, session_id)
    words = [
        word
        for line in transcript.lines
        for word in line.words
        if mark.word_from <= word.index <= mark.word_to
    ]
    try:
        start, end = snippet_window(
            min(w.start_ms for w in words), max(w.end_ms for w in words), item.duration_ms or 0
        )
    except ValueError as error:
        raise ProblemError(
            422,
            "card_phrase_too_long",
            "Choose a shorter marked phrase, lasting at most six seconds.",
        ) from error
    generation = uuid7()
    try:
        card_id = await repository.insert(
            db,
            {
                "id": uuid7(),
                "session_id": session_id,
                "user_id": learner,
                "mark_id": mark.id,
                "media_object_id": item.media_object_id,
                "at_ms": mark.at_ms,
                "written_form": new.written_form,
                "heard_form": new.heard_form,
                "snippet_start": start,
                "snippet_end": end,
                "generation": generation,
            },
        )
    except IntegrityError as error:
        # The mark can be removed by another request after list_marks returns.
        # Refuse that stale selection; unrelated integrity failures remain errors.
        if (
            getattr(error.orig, "sqlstate", None) != "23503"
            or getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            != "cards_mark_id_fkey"
        ):
            raise
        raise ProblemError(
            404, "mark_not_found", "There is no such mark in this session."
        ) from None
    if card_id is None:
        raise ProblemError(
            409,
            "card_limit_reached",
            "This session already has two cards. Delete one to free a slot.",
        )
    await enqueue(
        db,
        jobs.GENERATE,
        unique_key=f"card-snippet:{card_id}",
        lock=f"card-snippet:{card_id}",
        card_id=str(card_id),
        user_id=str(learner),
        generation_id=str(generation),
    )
    await analytics.record_card_created(db, learner, session_id, card_id)
    return await repository.get(db, card_id)


async def suggestions(
    db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID, worker_database: Database
) -> schemas.CardSuggestions:
    """FR-CA-4: the marks, likely connected-speech candidates first. Reading creates nothing."""
    await practice.require_reached(db, session_id, practice.Step.CARD)
    marks = await review.session_marks(db, session_id)
    phrases = await review.mark_phrases(db, worker_database, learner, session_id, marks)
    earlier = {
        normalize(phrase)
        for phrase in await review.earlier_phrases(db, worker_database, learner, session_id)
    }
    ranked = rank([Candidate(m.id, phrases[m.id], m.tag) for m in marks], earlier)
    return schemas.CardSuggestions(
        suggestions=[
            schemas.CardSuggestion(
                mark_id=item.mark_id,
                phrase=phrases[item.mark_id],
                suggested=item.suggested,
                reasons=list(item.reasons),
            )
            for item in ranked
        ]
    )


async def list_cards(
    db: AsyncSession, session_id: uuid.UUID | None, cursor: str | None, limit: int
) -> schemas.CardList:
    if session_id is not None:
        await practice.require_reached(db, session_id, practice.Step.CARD)
    try:
        decoded = cursors.decode(cursor) if cursor else None
    except cursors.InvalidCursor as error:
        raise ProblemError(422, "invalid_cursor", "Load the card list again.") from error
    rows = await repository.list_cards(db, session_id, decoded, limit + 1)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = cursors.encode(cursors.Cursor(rows[-1].created_at, rows[-1].id))
    return schemas.CardList(
        cards=rows,
        next_cursor=next_cursor,
        remaining=2 - await repository.count(db, session_id) if session_id else None,
    )


async def delete(db: AsyncSession, card_id: uuid.UUID) -> None:
    if not await repository.delete(db, card_id):
        raise ProblemError(404, "card_not_found", "There is no such card.")
    await enqueue(db, jobs.CLEANUP, unique_key="card-snippet-cleanup")


async def complete(db: AsyncSession, session_id: uuid.UUID) -> None:
    await repository.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.CARD)
    await practice.complete_step(db, session, practice.Step.CARD)


async def export_data(db: AsyncSession, learner: uuid.UUID) -> ExportPart:
    table = await learner_rows(
        db,
        "practice.cards",
        learner,
        order_by="created_at",
        omit=("snippet_key", "audio_generation"),
    )
    files = []
    for row in table.rows:
        audio = await repository.audio_row(db, row["id"], learner)
        if audio is None or audio.audio_status != "ready" or not audio.snippet_key:
            continue
        item = await content.find_content(db, audio.content_id)
        if item and item.source == "upload":
            files.append(ExportFile(audio.snippet_key, f"cards/{audio.id}/snippet.m4a"))
    return ExportPart(
        tables=(
            table,
            await learner_rows(db, "practice.card_reviews", learner, order_by="reviewed_at"),
            await learner_rows(db, "practice.card_snippet_cleanup", learner, order_by="created_at"),
            await learner_rows(
                db,
                "practice.card_snippet_writes",
                learner,
                omit=("id", "owner"),
                order_by="created_at",
            ),
        ),
        files=tuple(files),
    )


async def audio_url(
    db: AsyncSession, storage: Storage, learner: uuid.UUID, card_id: uuid.UUID
) -> str:
    row = await repository.audio_row(db, card_id, learner)
    if row is None:
        raise ProblemError(404, "card_not_found", "There is no such card.")
    if row.audio_status != "ready" or not row.snippet_key:
        raise ProblemError(
            409, "card_audio_not_ready", "This card's audio is not ready. Try again shortly."
        )
    return storage.signed_download(row.snippet_key, ttl_seconds=120).url


async def retry_audio(db: AsyncSession, learner: uuid.UUID, card_id: uuid.UUID) -> None:
    row = await repository.audio_row(db, card_id, learner, lock=True)
    if row is None:
        raise ProblemError(404, "card_not_found", "There is no such card.")
    if row.audio_status != "failed":
        raise ProblemError(409, "card_audio_not_failed", "Only failed card audio can be retried.")
    generation = uuid7()
    await db.execute(
        text(
            "UPDATE practice.cards SET audio_status='pending', audio_generation=:generation "
            "WHERE id=:id"
        ),
        {"id": card_id, "generation": generation},
    )
    await enqueue(
        db,
        jobs.GENERATE,
        unique_key=f"card-snippet:{card_id}:{generation}",
        lock=f"card-snippet:{card_id}",
        card_id=str(card_id),
        user_id=str(learner),
        generation_id=str(generation),
    )


async def review_history(
    db: AsyncSession, learner: uuid.UUID, card_id: uuid.UUID
) -> schemas.ReviewHistory:
    if await repository.audio_row(db, card_id, learner) is None:
        raise ProblemError(404, "card_not_found", "There is no such card.")
    return await repository.reviews(db, card_id)


async def record_review(
    db: AsyncSession, learner: uuid.UUID, card_id: uuid.UUID, body: schemas.ReviewResult
) -> schemas.CardReview:
    if await repository.audio_row(db, card_id, learner, lock=True) is None:
        raise ProblemError(404, "card_not_found", "There is no such card.")
    return await repository.insert_review(db, learner, card_id, uuid7(), body.result)


async def content_deletion_objects(
    db: AsyncSession,
    learner: uuid.UUID,
    sessions: list[uuid.UUID],
    manifest_prefixes: list[str],
) -> tuple[list[str], list[str]]:
    """Card writers must drain before the first content storage sweep."""
    rows = (
        await db.execute(
            text(
                "SELECT id FROM practice.cards WHERE user_id=:user AND "
                "session_id=ANY(:sessions) ORDER BY id FOR UPDATE"
            ),
            {"user": learner, "sessions": sessions},
        )
    ).all()
    # A deleted card can still have an uncertain writer. Its durable manifest,
    # rather than the surviving parent rows, defines the cleanup responsibility.
    ids = sorted(
        {row.id for row in rows}
        | {uuid.UUID(prefix.rstrip("/").rsplit("/", 1)[-1]) for prefix in manifest_prefixes}
    )
    await _require_no_content_writes(db, learner, ids)
    return [f"users/{learner}/cards/{card}/" for card in ids], []


async def _require_no_content_writes(
    db: AsyncSession, learner: uuid.UUID, ids: list[uuid.UUID]
) -> None:
    from datetime import UTC, datetime, timedelta

    from listenup.platform.jobs import Reschedule

    if ids and await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM practice.card_snippet_writes "
            "WHERE user_id=:user AND card_id=ANY(:ids))"
        ),
        {"user": learner, "ids": ids},
    ):
        raise Reschedule(datetime.now(UTC) + timedelta(minutes=1))


async def settle_content_deletion(
    db: AsyncSession, learner: uuid.UUID, prefixes: list[str]
) -> None:
    """Remove cascade tombstones only after their objects have been deleted."""
    ids = [uuid.UUID(prefix.rstrip("/").rsplit("/", 1)[-1]) for prefix in prefixes]
    await _require_no_content_writes(db, learner, ids)
    if ids:
        await db.execute(
            text(
                "DELETE FROM practice.card_snippet_cleanup WHERE user_id=:user AND "
                "card_id=ANY(:ids)"
            ),
            {"user": learner, "ids": ids},
        )


async def content_deletion_snapshot(
    db: AsyncSession, learner: uuid.UUID, sessions: list[uuid.UUID]
) -> list[str]:
    rows = await db.scalars(
        text("SELECT id FROM practice.cards WHERE user_id=:user AND session_id=ANY(:sessions)"),
        {"user": learner, "sessions": sessions},
    )
    return [f"users/{learner}/cards/{card}/" for card in rows]
