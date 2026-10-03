"""Per-transaction learner scoping for row-level security (Database Design 9.2)."""

import uuid

import pytest
from sqlalchemy import text

from listenup.platform.database import Database, set_learner
from tests.integration.conftest import conninfo_to_url


@pytest.fixture
async def database(migrated_url: str) -> Database:
    # One pooled connection, so every transaction below reuses the same connection.
    return Database(conninfo_to_url(migrated_url), pool_size=1)


async def current_learner(database: Database) -> str | None:
    async with database.transaction() as session:
        value = await session.scalar(text("SELECT current_setting('app.user_id', true)"))
    return value or None


@pytest.mark.anyio
async def test_the_learner_is_set_for_one_transaction_only(database: Database) -> None:
    learner = uuid.uuid4()
    try:
        async with database.transaction(learner) as session:
            inside = await session.scalar(text("SELECT current_setting('app.user_id', true)"))
        assert inside == str(learner)
        # Same pooled connection, next transaction: the setting is gone.
        assert await current_learner(database) is None
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_a_failed_transaction_does_not_keep_the_learner(database: Database) -> None:
    try:
        with pytest.raises(RuntimeError):
            async with database.transaction(uuid.uuid4()):
                raise RuntimeError("handler failed")
        assert await current_learner(database) is None
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_row_level_security_follows_the_learner(
    database: Database, learner: uuid.UUID
) -> None:
    other = uuid.uuid4()
    try:
        async with database.transaction() as session:
            await session.execute(text("SET LOCAL ROLE listenup_api"))
            await set_learner(session, learner)
            await session.execute(
                text(
                    "INSERT INTO ops.idempotency_keys (user_id, key, request_hash) "
                    "VALUES (:user_id, 'k', '\\x00')"
                ),
                {"user_id": learner},
            )
            mine = await session.scalar(text("SELECT count(*) FROM ops.idempotency_keys"))
            await set_learner(session, other)
            theirs = await session.scalar(text("SELECT count(*) FROM ops.idempotency_keys"))
            await session.rollback()
        assert (mine, theirs) == (1, 0)
    finally:
        await database.dispose()
