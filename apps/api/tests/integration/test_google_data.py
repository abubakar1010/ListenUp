"""Linked identities export safely and disappear with their owning account."""

import asyncio
import uuid

import psycopg

from listenup.modules.identity.service import export_data
from listenup.platform.database import Database


def test_google_identity_export_and_cascade(
    migrated_url: str, learner: uuid.UUID, api_role_url: str
) -> None:
    subject = str(uuid.uuid4())
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.oauth_accounts (provider, subject, user_id) "
            "VALUES ('google', %s, %s)",
            [subject, learner],
        )
        conn.execute(
            "INSERT INTO identity.oidc_flows "
            "(token_hash, browser_hash, user_id, purpose, data, expires_at) "
            "VALUES ('secret-hash', 'browser-secret', %s, 'delete', '{\"secret\": \"verifier\"}', "
            "now() + interval '10 minutes')",
            [learner],
        )

    async def read() -> object:
        db = Database(api_role_url)
        try:
            async with db.transaction(learner) as session:
                return await export_data(session, learner)
        finally:
            await db.dispose()

    part = asyncio.run(read())
    tables = {table.name: table.rows for table in part.tables}
    assert tables["identity.oauth_accounts"][0]["subject"] == subject
    flows = tables["identity.oidc_flows"]
    assert len(flows) == 1
    assert not {"token_hash", "browser_hash", "data"} & flows[0].keys()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM identity.users WHERE id = %s", [learner])
        assert conn.execute(
            "SELECT count(*) FROM identity.oauth_accounts WHERE user_id = %s", [learner]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM identity.oidc_flows WHERE user_id = %s", [learner]
        ).fetchone() == (0,)


def test_google_identities_are_scoped_by_the_restricted_api_role(
    migrated_url: str, api_role_url: str, learner: uuid.UUID
) -> None:
    other = uuid.uuid4()
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
            [other, f"{other}@example.com"],
        )
        conn.execute(
            "INSERT INTO identity.oauth_accounts (provider, subject, user_id) "
            "VALUES ('google', %s, %s), ('google', %s, %s)",
            [mine, learner, theirs, other],
        )
    try:
        with psycopg.connect(api_role_url) as conn:
            assert conn.execute("SELECT subject FROM identity.oauth_accounts").fetchall() == []
            conn.execute("SELECT set_config('app.user_id', %s, true)", [str(learner)])
            assert conn.execute("SELECT subject FROM identity.oauth_accounts").fetchall() == [
                (mine,)
            ]
            import pytest

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "INSERT INTO identity.oauth_accounts (provider, subject, user_id) "
                    "VALUES ('google', %s, %s)",
                    [str(uuid.uuid4()), other],
                )
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as conn:
            conn.execute("DELETE FROM identity.users WHERE id = %s", [other])
