"""Cards public boundary: FR-CA-1..3, two live cards per session (D14)."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.cards import repository, schemas
from listenup.modules.cards.domain import cursor as cursors
from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.review import service as review
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows
from listenup.platform.ids import uuid7


async def create(
    db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID, new: schemas.NewCard
) -> schemas.Card:
    await repository.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.CARD)
    marks = await review.list_marks(db, session_id)
    mark = next((mark for mark in marks if mark.id == new.mark_id), None)
    if mark is None:
        raise ProblemError(404, "mark_not_found", "There is no such mark in this session.")
    item = await content.get_content(db, learner, session.content_id)
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
    await analytics.record_card_created(db, learner, session_id, card_id)
    return await repository.get(db, card_id)


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


async def complete(db: AsyncSession, session_id: uuid.UUID) -> None:
    await repository.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.CARD)
    await practice.complete_step(db, session, practice.Step.CARD)


async def export_data(db: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(
        tables=(await learner_rows(db, "practice.cards", learner, order_by="created_at"),)
    )
