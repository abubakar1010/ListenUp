"""Constraints, triggers and role settings of the identity schema."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]


def add_user(conn: Conn, email: str, **values: object) -> uuid.UUID:
    user_id = uuid.uuid4()
    columns = ["id", "email", *values]
    conn.execute(
        f"INSERT INTO identity.users ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))})",
        [user_id, email, *values.values()],
    )
    return user_id


def test_email_is_unique_regardless_of_case(conn: Conn) -> None:
    add_user(conn, "Learner@Example.com")
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_user(conn, "learner@example.com")


def test_pending_deletion_needs_a_scheduled_date(conn: Conn) -> None:
    with conn.transaction(), pytest.raises(psycopg.errors.CheckViolation):
        add_user(conn, "a@example.com", status="pending_deletion")
    with conn.transaction(), pytest.raises(psycopg.errors.CheckViolation):
        add_user(conn, "b@example.com", deletion_scheduled_at=datetime.now(UTC))

    add_user(
        conn,
        "c@example.com",
        status="pending_deletion",
        deletion_scheduled_at=datetime.now(UTC) + timedelta(days=7),
    )


def test_unknown_status_is_refused(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        add_user(conn, "a@example.com", status="banned")


def test_updated_at_moves_on_update(conn: Conn) -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    user_id = add_user(conn, "a@example.com", created_at=old, updated_at=old)

    conn.execute("UPDATE identity.users SET display_name = 'A' WHERE id = %s", [user_id])

    row = conn.execute("SELECT updated_at FROM identity.users WHERE id = %s", [user_id]).fetchone()
    assert row is not None
    assert row[0] > old


def test_deleting_a_user_removes_their_login_sessions(conn: Conn) -> None:
    user_id = add_user(conn, "a@example.com")
    conn.execute(
        "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s, now() + interval '30 days')",
        [uuid.uuid4(), user_id, b"token"],
    )

    conn.execute("DELETE FROM identity.users WHERE id = %s", [user_id])

    row = conn.execute(
        "SELECT count(*) FROM identity.auth_sessions WHERE user_id = %s", [user_id]
    ).fetchone()
    assert row == (0,)


@pytest.mark.parametrize(
    ("role", "setting"),
    [
        ("listenup_api", "statement_timeout=5s"),
        ("listenup_api", "idle_in_transaction_session_timeout=30s"),
        ("listenup_worker", "statement_timeout=60s"),
        ("listenup_worker", "idle_in_transaction_session_timeout=30s"),
    ],
)
def test_role_timeouts(conn: Conn, role: str, setting: str) -> None:
    row = conn.execute(
        "SELECT s.setconfig FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole "
        "WHERE r.rolname = %s AND s.setdatabase = 0",
        [role],
    ).fetchone()
    assert row is not None
    assert setting in row[0]  # type: ignore[operator]


def test_worker_role_bypasses_row_level_security(conn: Conn) -> None:
    row = conn.execute(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'listenup_worker'"
    ).fetchone()
    assert row == (True,)
