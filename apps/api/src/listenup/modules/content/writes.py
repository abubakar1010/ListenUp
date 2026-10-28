"""Durable conversion writers, admitted under the content deletion lock (ADR 0085)."""

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import repository
from listenup.modules.identity import service as identity
from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.database import Database
from listenup.platform.jobs import PermanentError
from listenup.platform.storage import StorageWriteUncertain


@asynccontextmanager
async def registered_write(
    database: Database, learner: uuid.UUID, media: uuid.UUID, content: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    writer = uuid.uuid4()
    registered = uncertain = False
    try:
        async with database.transaction(learner) as db:
            if not await identity.hold_active_account(db, learner):
                raise PermanentError("The account is no longer active.")
            if not await repository.retain_content(db, learner, content):
                raise PermanentError("Content has been deleted.")
            await db.execute(
                text(
                    "INSERT INTO content.media_writes(id,media_object_id,user_id,owner) "
                    "VALUES (:id,:media,:user,:owner)"
                ),
                {
                    "id": writer,
                    "media": media,
                    "user": learner,
                    "owner": f"{socket.gethostname()}:{os.getpid()}",
                },
            )
            registered = True
        async with database.transaction(learner) as db:
            await db.execute(text("SET LOCAL idle_in_transaction_session_timeout = '16min'"))
            if not await identity.hold_active_account(db, learner):
                raise PermanentError("The account is no longer active.")
            if not await repository.retain_content(db, learner, content):
                raise PermanentError("Content has been deleted.")
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
                        text("DELETE FROM content.media_writes WHERE id=:id"), {"id": writer}
                    )

            await finish_on_cancel(release())


async def store(operation: Awaitable[None]) -> None:
    """Drain cancellation and preserve a fence when either storage PUT is uncertain."""

    async def tracked() -> None:
        try:
            await operation
        except asyncio.CancelledError:
            # Shutdown may cancel this child directly while its executor or remote
            # PUT is still active. Preserve the registration for reconciliation.
            raise asyncio.CancelledError from StorageWriteUncertain(
                "Storage task ended before the remote write was confirmed."
            )
        except Exception as error:
            raise StorageWriteUncertain(
                "Reconcile the conversion upload before cleanup."
            ) from error

    await finish_on_cancel(tracked())
