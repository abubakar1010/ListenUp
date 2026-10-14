"""A committed fence keeps purge out even if an upload's DB connection dies (DR-1)."""

import os
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.platform.cancellation import finish_on_cancel
from listenup.platform.database import Database
from listenup.platform.storage import StorageWriteUncertain

AccountHold = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]


class StorageWriteInProgress(Exception):
    """Retry purge once a registered writer has settled; never sweep past it."""


async def require_no_storage_writes(session: AsyncSession, learner: uuid.UUID) -> None:
    """Call after taking the exclusive account lock, before the first purge sweep."""
    if await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM ops.storage_writes WHERE subject_user_id = :learner)"),
        {"learner": learner},
    ):
        raise StorageWriteInProgress("account has an unfinished storage writer")


@asynccontextmanager
async def storage_transaction(
    database: Database, learner: uuid.UUID, hold_account: AccountHold, timeout: timedelta
) -> AsyncIterator[tuple[AsyncSession, bool]]:
    """Register under the account lock, then retain a fence through result persistence.

    The committed registration survives connection loss. Upload callers must drain
    their writes with finish_on_cancel before leaving this scope. No time-based
    expiry is safe: a killed process leaves a fence for operator reconciliation.
    """
    writer = uuid.uuid4()
    registered = False
    uncertain = False
    try:
        async with database.transaction(learner) as session:
            if await hold_account(session, learner):
                await session.execute(
                    text(
                        "INSERT INTO ops.storage_writes (id, subject_user_id, owner) "
                        "VALUES (:id, :user, :owner)"
                    ),
                    {
                        "id": writer,
                        "user": learner,
                        "owner": f"{socket.gethostname()}:{os.getpid()}",
                    },
                )
                registered = True
        async with database.transaction(learner) as session:
            # The worker's normal 30 s limit is too short for bounded S3 work.
            # A minute also allows result persistence after cancellation draining.
            await session.execute(
                text("SELECT set_config('idle_in_transaction_session_timeout', :timeout, true)"),
                {"timeout": f"{int(timeout.total_seconds()) + 60}s"},
            )
            writable = registered and await hold_account(session, learner)
            try:
                yield session, writable
            except BaseException as error:
                # Cancellation keeps the upload's failure as its cause. Inspect
                # it before rollback can replace it with a connection exception.
                failure: BaseException | None = error
                while failure is not None:
                    if isinstance(failure, StorageWriteUncertain):
                        uncertain = True
                        break
                    failure = failure.__cause__
                raise
            if registered:
                await session.execute(
                    text("DELETE FROM ops.storage_writes WHERE id = :id"), {"id": writer}
                )
        registered = False
    finally:
        if registered and not uncertain:

            async def release() -> None:
                async with database.transaction(learner) as session:
                    await session.execute(
                        text("DELETE FROM ops.storage_writes WHERE id = :id"), {"id": writer}
                    )

            await finish_on_cancel(release())
