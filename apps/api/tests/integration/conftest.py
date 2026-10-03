"""Integration tests against a real PostgreSQL 16 server.

Each test run creates a throwaway database on the server named by
LISTENUP_DATABASE_URL, migrates it to head and drops it afterwards. The tests are
skipped when no server is reachable, unless LISTENUP_REQUIRE_DB=1 (set in CI), in which
case an unreachable server is an error.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql

from listenup.platform.config import get_settings
from listenup.platform.db import to_sqlalchemy_url

API_DIR = Path(__file__).resolve().parents[2]


def server_url() -> str:
    return get_settings().database_url


def with_dbname(url: str, dbname: str) -> str:
    return psycopg.conninfo.make_conninfo(url, dbname=dbname)


def conninfo_to_url(conninfo: str) -> str:
    params = psycopg.conninfo.conninfo_to_dict(conninfo)
    return "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(
        user=params.get("user", ""),
        password=params.get("password", ""),
        host=params.get("host", "localhost"),
        port=params.get("port", 5432),
        dbname=params["dbname"],
    )


def alembic_config(conninfo: str) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", to_sqlalchemy_url(conninfo_to_url(conninfo)))
    return config


@pytest.fixture(scope="session")
def admin_url() -> str:
    url = server_url()
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as error:
        if os.environ.get("LISTENUP_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"PostgreSQL is not reachable: {error}")
    return url


@pytest.fixture(scope="session")
def make_database(admin_url: str) -> Iterator[object]:
    """Factory for empty throwaway databases, dropped at the end of the run."""
    created: list[str] = []

    def make() -> str:
        name = f"listenup_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created.append(name)
        return with_dbname(admin_url, name)

    yield make
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for name in created:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
def migrated_url(make_database: object) -> str:
    from alembic import command

    url: str = make_database()  # type: ignore[operator]
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def conn(migrated_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A connection whose work is rolled back after the test."""
    with psycopg.connect(migrated_url) as connection:
        yield connection
        connection.rollback()


@pytest.fixture
def learner(migrated_url: str) -> Iterator[uuid.UUID]:
    """A committed learner, visible to the app's own connections; removed afterwards."""
    user_id = uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
            [user_id, f"{user_id}@example.com"],
        )
        yield user_id
        connection.execute("DELETE FROM identity.users WHERE id = %s", [user_id])


def with_csrf(client: TestClient) -> TestClient:
    """Fetch the CSRF cookie once and send it back as the header, as the web app does."""
    client.get("/api/v1/health")
    token = next(value for name, value in client.cookies.items() if name.endswith("listenup_csrf"))
    client.headers["X-CSRF-Token"] = token
    return client


@pytest.fixture(autouse=True)
def fresh_rate_counters(request: pytest.FixtureRequest) -> None:
    """Rate limits are shared state; each test starts with none counted."""
    if "migrated_url" not in request.fixturenames:
        return
    url: str = request.getfixturevalue("migrated_url")
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("DELETE FROM ops.rate_counters")


@pytest.fixture(scope="session")
def api_role_url(migrated_url: str) -> str:
    """A login role with only listenup_api's rights, so row-level security applies.

    The migration owner bypasses row-level security, so tests that connect as it
    would miss a query that the real API role cannot see.
    """
    with psycopg.connect(migrated_url, autocommit=True) as connection:
        connection.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_api_test') THEN
                CREATE ROLE listenup_api_test LOGIN PASSWORD 'listenup-test';
              END IF;
            END $$;
            GRANT listenup_api TO listenup_api_test;
        """)
    params = psycopg.conninfo.conninfo_to_dict(migrated_url)
    params.update(user="listenup_api_test", password="listenup-test")
    return conninfo_to_url(psycopg.conninfo.make_conninfo(**params))  # type: ignore[arg-type]
