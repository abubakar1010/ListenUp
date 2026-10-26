"""Durable snippet writers survive lost DB locks and killed workers (DR-1)."""

import os
import socket
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.cards import repository
from listenup.modules.identity import service as identity
from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.database import Database
from listenup.platform.jobs import PermanentError
from listenup.platform.storage import StorageWriteUncertain


@asynccontextmanager
async def registered_write(
    database: Database, learner: uuid.UUID, card: uuid.UUID, generation: uuid.UUID | None
) -> AsyncIterator[AsyncSession]:
    writer = uuid.uuid4()
    registered = uncertain = False
    try:
        async with database.transaction(learner) as db:
            if not await identity.hold_active_account(db, learner):
                raise PermanentError("The account is no longer active.")
            row = await repository.audio_row(db, card, learner, lock=True)
            if not row or row.audio_status != "pending" or row.audio_generation != generation:
                # Still yield a transaction; the caller rechecks the card before writing.
                pass
            else:
                await db.execute(
                    text(
                        "INSERT INTO practice.card_snippet_writes(id,card_id,user_id,owner) "
                        "VALUES (:id,:card,:user,:owner)"
                    ),
                    {
                        "id": writer,
                        "card": card,
                        "user": learner,
                        "owner": f"{socket.gethostname()}:{os.getpid()}",
                    },
                )
                registered = True
        async with database.transaction(learner) as db:
            # Bound uploads by the job deadline without the normal 30s idle disconnect.
            await db.execute(text("SET LOCAL idle_in_transaction_session_timeout = '11min'"))
            if not await identity.hold_active_account(db, learner):
                raise PermanentError("The account is no longer active.")
            try:
                yield db
            except BaseException as error:
                failure: BaseException | None = error
                while failure is not None:
                    if isinstance(failure, StorageWriteUncertain):
                        uncertain = True
                        break
                    failure = failure.__cause__
                raise
    finally:
        if registered and not uncertain:

            async def release() -> None:
                async with database.transaction(learner) as db:
                    await db.execute(
                        text("DELETE FROM practice.card_snippet_writes WHERE id=:id"),
                        {"id": writer},
                    )

            await finish_on_cancel(release())
