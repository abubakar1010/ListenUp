"""Row-level security (Database Design 9.2; NFR-SEC-2; acceptance criteria of #27).

Each test switches to a service role with SET LOCAL ROLE, so the checks run with the
same rights as the API or a worker, not as the migration owner.
"""

import uuid

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]


def add_learner(conn: Conn, email: str, token: bytes, expires: str = "30 days") -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute("INSERT INTO identity.users (id, email) VALUES (%s, %s)", [user_id, email])
    conn.execute(
        "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s, now() + %s::interval)",
        [uuid.uuid4(), user_id, token, expires],
    )
    return user_id


@pytest.fixture
def learners(conn: Conn) -> tuple[uuid.UUID, uuid.UUID]:
    a = add_learner(conn, "a@example.com", b"token-a")
    b = add_learner(conn, "b@example.com", b"token-b")
    return a, b


def act_as(conn: Conn, role: str, learner: uuid.UUID | None = None) -> None:
    conn.execute(f"SET LOCAL ROLE {role}")
    if learner is not None:
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(learner)])


def visible_sessions(conn: Conn) -> list[uuid.UUID]:
    return [row[0] for row in conn.execute("SELECT user_id FROM identity.auth_sessions")]  # type: ignore[misc]


def test_no_learner_set_returns_no_rows(conn: Conn, learners: object) -> None:
    act_as(conn, "listenup_api")
    assert visible_sessions(conn) == []


def test_an_empty_learner_setting_also_returns_no_rows(conn: Conn, learners: object) -> None:
    act_as(conn, "listenup_api")
    conn.execute("SELECT set_config('app.user_id', '', true)")
    assert visible_sessions(conn) == []


def test_a_learner_sees_only_their_own_rows(
    conn: Conn, learners: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, _ = learners
    act_as(conn, "listenup_api", a)
    assert visible_sessions(conn) == [a]


def test_a_learner_cannot_change_another_learners_rows(
    conn: Conn, learners: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = learners
    act_as(conn, "listenup_api", a)

    updated = conn.execute(
        "UPDATE identity.auth_sessions SET last_seen_at = now() WHERE user_id = %s", [b]
    )
    deleted = conn.execute("DELETE FROM identity.auth_sessions WHERE user_id = %s", [b])
    assert (updated.rowcount, deleted.rowcount) == (0, 0)


def test_a_learner_cannot_write_rows_for_another_learner(
    conn: Conn, learners: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = learners
    act_as(conn, "listenup_api", a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
            "VALUES (%s, %s, 'x', now())",
            [uuid.uuid4(), b],
        )


def test_a_cookie_resolves_to_its_learner_only_while_live(conn: Conn) -> None:
    live = add_learner(conn, "live@example.com", b"live")
    add_learner(conn, "old@example.com", b"old", expires="-1 minute")
    act_as(conn, "listenup_api")

    def resolve(token: bytes) -> object:
        row = conn.execute("SELECT identity.resolve_auth_session(%s)", [token]).fetchone()
        return row[0] if row else None

    assert resolve(b"live") == live
    assert resolve(b"old") is None
    assert resolve(b"unknown") is None


def test_workers_see_every_learner(conn: Conn, learners: tuple[uuid.UUID, uuid.UUID]) -> None:
    act_as(conn, "listenup_worker")
    assert set(learners) <= set(visible_sessions(conn))


def test_the_read_only_role_cannot_read_identity(conn: Conn) -> None:
    act_as(conn, "listenup_readonly")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT count(*) FROM identity.users")


def test_only_the_api_may_resolve_cookies(conn: Conn) -> None:
    act_as(conn, "listenup_readonly")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT identity.resolve_auth_session('x')")
