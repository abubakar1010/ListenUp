"""Marks in the database (migration 58_marks; issue #58, Database Design 5).

The database repeats the mark rules that stored data alone can check: a word range
that runs forwards, a short note, a known source, and a mark that belongs to the
learner of its session. Rows are private to their learner under row-level security.
"""

import uuid

import psycopg
import pytest

from tests.integration.test_practice_schema import add_content, add_session, add_user

Conn = psycopg.Connection[tuple[object, ...]]


def add_mark(
    conn: Conn,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    word_from: int = 0,
    word_to: int = 0,
    at_ms: int = 0,
    note: str | None = None,
    source: str = "manual",
    tag: str | None = None,
) -> uuid.UUID:
    mark_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO practice.marks "
        "(id, session_id, user_id, word_from, word_to, at_ms, note, source, tag) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [mark_id, session_id, user_id, word_from, word_to, at_ms, note, source, tag],
    )
    return mark_id


@pytest.fixture
def owner(migrated_url: str):
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def session(owner: Conn) -> tuple[uuid.UUID, uuid.UUID]:
    user = add_user(owner)
    return user, add_session(owner, user, add_content(owner, user))


def test_a_mark_stores_word_range_audio_time_and_defaults(owner, session):
    user, session_id = session
    mark = add_mark(owner, user, session_id, word_from=3, word_to=5, at_ms=12_000, note="linking")
    row = owner.execute(
        "SELECT word_from, word_to, at_ms, note, source, status, tag, created_at IS NOT NULL "
        "FROM practice.marks WHERE id = %s",
        [mark],
    ).fetchone()
    assert row == (3, 5, 12_000, "linking", "manual", "confirmed", None, True)


@pytest.mark.parametrize(
    "values",
    [
        {"word_from": -1, "word_to": 0},
        {"word_from": 4, "word_to": 3},
        {"at_ms": -1},
        {"note": "x" * 501},
        {"source": "guess"},
        {"tag": "accent"},
    ],
)
def test_the_database_refuses_invalid_marks(owner, session, values):
    user, session_id = session
    with pytest.raises(psycopg.errors.CheckViolation):
        add_mark(owner, user, session_id, **values)


def test_a_note_of_500_characters_is_allowed(owner, session):
    user, session_id = session
    add_mark(owner, user, session_id, note="x" * 500)


def test_one_mark_per_word_range_in_a_session(owner, session):
    user, session_id = session
    add_mark(owner, user, session_id, word_from=1, word_to=2)
    add_mark(owner, user, session_id, word_from=1, word_to=3)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_mark(owner, user, session_id, word_from=1, word_to=2)


def test_a_mark_cannot_belong_to_another_learners_session(owner, session):
    _, session_id = session
    stranger = add_user(owner)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_mark(owner, stranger, session_id)


def test_marks_go_with_their_session_and_account(owner, session):
    user, session_id = session
    add_mark(owner, user, session_id)
    count = "SELECT count(*) FROM practice.marks WHERE user_id = %s"
    owner.execute("DELETE FROM practice.sessions WHERE id = %s", [session_id])
    assert owner.execute(count, [user]).fetchone() == (0,)
    add_mark(owner, user, add_session_as_owner(owner, user))
    owner.execute("DELETE FROM identity.users WHERE id = %s", [user])
    assert owner.execute(count, [user]).fetchone() == (0,)


def test_the_api_role_sees_and_changes_only_its_learners_marks(owner, session, api_role_url):
    user, session_id = session
    other = add_user(owner)
    other_mark = add_mark(owner, other, add_session(owner, other, add_content(owner, other)))
    with psycopg.connect(api_role_url) as conn:
        assert conn.execute("SELECT count(*) FROM practice.marks").fetchone() == (0,)
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(user)])
        mark = add_mark(conn, user, session_id, word_from=2, word_to=2)
        conn.execute("UPDATE practice.marks SET note = 'mine' WHERE id = %s", [mark])
        assert conn.execute("SELECT id, note FROM practice.marks").fetchall() == [(mark, "mine")]
        assert conn.execute("DELETE FROM practice.marks WHERE id = %s", [other_mark]).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            add_mark(conn, other, add_session_as_owner(owner, other))
        conn.rollback()
    assert owner.execute(
        "SELECT count(*) FROM practice.marks WHERE id = %s", [other_mark]
    ).fetchone() == (1,)


def add_session_as_owner(owner: Conn, user: uuid.UUID) -> uuid.UUID:
    return add_session(owner, user, add_content(owner, user))
