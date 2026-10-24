"""Cards constraints and grants as a restricted learner (ADR 0013)."""

import uuid

import psycopg
import pytest

from tests.integration import test_marks_schema as marks
from tests.integration.test_practice_schema import add_user

owner = marks.owner
session = marks.session


def insert(db, user, session_id, *, slot=1, written="a", heard="b"):
    card = uuid.uuid4()
    db.execute(
        "INSERT INTO practice.cards "
        "(id, user_id, session_id, slot, written_form, heard_form, at_ms) "
        "VALUES (%s,%s,%s,%s,%s,%s,0)",
        [card, user, session_id, slot, written, heard],
    )
    return card


@pytest.mark.parametrize(
    "values",
    [
        {"slot": 0},
        {"slot": 3},
        {"written": ""},
        {"written": "a" * 101},
        {"heard": ""},
        {"heard": "a" * 101},
    ],
)
def test_db_refuses_invalid_cards(owner, session, values):
    user, sid = session
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(owner, user, sid, **values)


def test_db_unique_slots_and_composite_owner(owner, session):
    user, sid = session
    insert(owner, user, sid)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert(owner, user, sid)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert(owner, add_user(owner), sid, slot=2)


def test_cards_rls_grants_and_cascade(owner, session, api_role_url):
    user, sid = session
    other = add_user(owner)
    card = insert(owner, user, sid)
    with psycopg.connect(api_role_url) as db:
        assert db.execute("SELECT id FROM practice.cards").fetchall() == []
        db.execute("SELECT set_config('app.user_id', %s, true)", [str(other)])
        assert db.execute("DELETE FROM practice.cards WHERE id=%s", [card]).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(db, user, sid, slot=2)
        db.rollback()
        db.execute("SELECT set_config('app.user_id', %s, true)", [str(user)])
        assert db.execute("SELECT id FROM practice.cards").fetchall() == [(card,)]
        assert db.execute("DELETE FROM practice.cards WHERE id=%s", [card]).rowcount == 1
        insert(db, user, sid, slot=2)
    owner.execute("DELETE FROM identity.users WHERE id=%s", [user])
    assert owner.execute(
        "SELECT count(*) FROM practice.cards WHERE session_id=%s", [sid]
    ).fetchone() == (0,)
