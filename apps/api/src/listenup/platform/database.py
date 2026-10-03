"""Async database access with the learner set for row-level security.

Each request gets one session inside one transaction. Once the caller is known, the
request calls `set_learner`, which runs `set_config('app.user_id', ..., true)`: the
setting is local to the transaction, so it can never leak into another request that
reuses the pooled connection (Database Design 9.2).

Route handlers take the session with `DbSession`. Its dependency uses
`scope="function"`, so the transaction commits as soon as the handler returns and
before the response is sent: a failed commit becomes an error response instead of a
success the database never kept.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from listenup.platform.db import to_sqlalchemy_url


class Database:
    def __init__(self, database_url: str, pool_size: int = 5) -> None:
        self.engine: AsyncEngine = create_async_engine(
            to_sqlalchemy_url(database_url), pool_size=pool_size, pool_pre_ping=True
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self, learner: uuid.UUID | None = None) -> AsyncIterator[AsyncSession]:
        """A session in one transaction, committed on success and rolled back on error."""
        async with self._sessions() as session, session.begin():
            if learner is not None:
                await set_learner(session, learner)
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


async def set_learner(session: AsyncSession, learner: uuid.UUID) -> None:
    """Scope every following statement in this transaction to one learner's rows."""
    await session.execute(
        text("SELECT set_config('app.user_id', :learner, true)"), {"learner": str(learner)}
    )


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


async def _request_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_database(request).transaction() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(_request_session, scope="function")]
