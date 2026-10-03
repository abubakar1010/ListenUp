"""Practice sessions and steps in the database (migration 0007; issue #47).

The database repeats the plan rules that can be checked from stored data alone
(Database Design 8): these tests write SQL directly, as a bug or a manual fix would,
and expect the database to refuse. Most run as the API role, so row-level security
applies.
"""

import uuid

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]

PATH = ("dictation", "transcript", "card", "shadow")


def add_user(conn: Conn) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO identity.users (id, email) VALUES (%s, %s)", [user_id, f"{user_id}@ex.com"]
    )
    return user_id


def add_content(conn: Conn, user_id: uuid.UUID) -> uuid.UUID:
    media_id, content_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        "INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by) "
        "VALUES (%s, %s, 'upload', %s)",
        [media_id, f"upload:{user_id}:{media_id}", user_id],
    )
    conn.execute(
        "INSERT INTO content.contents (id, user_id, media_object_id, title) "
        "VALUES (%s, %s, %s, 'Clip')",
        [content_id, user_id, media_id],
    )
    return content_id


def add_session(
    conn: Conn,
    user_id: uuid.UUID,
    content_id: uuid.UUID,
    *,
    path: tuple[str, ...] = PATH,
    passage: str = "[0,120000)",
) -> uuid.UUID:
    session_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO practice.sessions (id, user_id, content_id, passage, entry, current_step) "
        "VALUES (%s, %s, %s, %s::int4range, %s, %s)",
        [session_id, user_id, content_id, passage, "dictation", path[0]],
    )
    for position, step in enumerate(path, start=1):
        conn.execute(
            "INSERT INTO practice.session_steps (session_id, user_id, step, position, status) "
            "VALUES (%s, %s, %s, %s, %s)",
            [session_id, user_id, step, position, "open" if position == 1 else "locked"],
        )
    return session_id


def set_step(conn: Conn, session_id: uuid.UUID, step: str, status: str) -> None:
    conn.execute(
        "UPDATE practice.session_steps SET status = %s WHERE session_id = %s AND step = %s",
        [status, session_id, step],
    )


def act_as_learner(conn: Conn, learner: uuid.UUID) -> None:
    conn.execute("SET LOCAL ROLE listenup_api")
    conn.execute("SELECT set_config('app.user_id', %s, true)", [str(learner)])


@pytest.fixture
def owned(conn: Conn) -> tuple[uuid.UUID, uuid.UUID]:
    """A learner with one content item, acting as the API role from here on."""
    learner = add_user(conn)
    content = add_content(conn, learner)
    act_as_learner(conn, learner)
    return learner, content


def refused(conn: Conn, prefix: str) -> pytest.RaisesExc[psycopg.errors.CheckViolation]:
    return pytest.raises(psycopg.errors.CheckViolation, match=f"^{prefix}")


# session_steps_order (FR-PL-4)


def test_a_step_cannot_open_before_the_one_before_it_is_finished(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)

    with refused(conn, "step_locked"):
        set_step(conn, session, "transcript", "open")


def test_a_step_opens_after_the_one_before_it_is_done_or_skipped(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)

    set_step(conn, session, "dictation", "done")
    set_step(conn, session, "transcript", "open")
    set_step(conn, session, "transcript", "done")
    set_step(conn, session, "card", "open")
    set_step(conn, session, "card", "skipped")
    set_step(conn, session, "shadow", "open")


def test_skipping_ahead_two_steps_is_refused(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)
    set_step(conn, session, "dictation", "done")

    with refused(conn, "step_locked"):
        set_step(conn, session, "card", "open")


def test_an_open_step_cannot_be_inserted_out_of_order(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    learner, content = owned
    session = add_session(conn, learner, content, path=("dictation",))

    with refused(conn, "step_locked"):
        conn.execute(
            "INSERT INTO practice.session_steps (session_id, user_id, step, position, status) "
            "VALUES (%s, %s, 'transcript', 2, 'open')",
            [session, learner],
        )


def test_the_step_order_error_maps_to_the_api_code(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)

    with refused(conn, "step_locked") as error:
        set_step(conn, session, "shadow", "open")
    assert error.value.diag.message_primary == "step_locked: shadow cannot open before step 3"


# sessions_entry_lock (FR-PL-5)


def test_the_entry_changes_freely_before_the_lock(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)

    conn.execute("UPDATE practice.sessions SET entry = 'both' WHERE id = %s", [session])


def test_the_entry_cannot_change_once_locked(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)
    conn.execute("UPDATE practice.sessions SET entry_locked_at = now() WHERE id = %s", [session])

    with refused(conn, "entry_locked"):
        conn.execute("UPDATE practice.sessions SET entry = 'both' WHERE id = %s", [session])


def test_a_locked_entry_can_be_written_with_its_own_value(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    session = add_session(conn, *owned)
    conn.execute("UPDATE practice.sessions SET entry_locked_at = now() WHERE id = %s", [session])

    conn.execute("UPDATE practice.sessions SET entry = 'dictation' WHERE id = %s", [session])


# Constraints (FR-PL-7, C2)


@pytest.mark.parametrize("step", ["dictation", "transcript"])
def test_only_card_and_shadow_can_be_skipped(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID], step: str
) -> None:
    session = add_session(conn, *owned)
    set_step(conn, session, "dictation", "done")

    with pytest.raises(psycopg.errors.CheckViolation, match="session_steps_check"):
        set_step(conn, session, step, "skipped")


@pytest.mark.parametrize(
    "passage", ["[0,29999)", "[0,900001)", "empty", "[0,)", "(,60000)", "[-5000,40000)"]
)
def test_the_passage_is_30_seconds_to_15_minutes(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID], passage: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        add_session(conn, *owned, passage=passage)


@pytest.mark.parametrize("passage", ["[0,30000)", "[1000,901000)"])
def test_passage_bounds_are_accepted(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID], passage: str
) -> None:
    add_session(conn, *owned, passage=passage)


def test_a_plan_has_at_most_five_positions_each_used_once(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    learner, content = owned
    session = add_session(conn, learner, content)

    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute(
            "INSERT INTO practice.session_steps (session_id, user_id, step, position, status) "
            "VALUES (%s, %s, 'blind', 2, 'locked')",
            [session, learner],
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO practice.session_steps (session_id, user_id, step, position, status) "
            "VALUES (%s, %s, 'blind', 6, 'locked')",
            [session, learner],
        )


# Ownership (NFR-SEC-2)


def test_a_learner_sees_only_their_own_sessions_and_steps(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    mine = add_session(conn, a, add_content(conn, a))
    add_session(conn, b, add_content(conn, b))
    act_as_learner(conn, a)

    assert [r[0] for r in conn.execute("SELECT id FROM practice.sessions")] == [mine]
    assert {r[0] for r in conn.execute("SELECT session_id FROM practice.session_steps")} == {mine}


def test_a_learner_cannot_change_another_learners_steps(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    theirs = add_session(conn, b, add_content(conn, b))
    act_as_learner(conn, a)

    updated = conn.execute(
        "UPDATE practice.session_steps SET status = 'done' WHERE session_id = %s", [theirs]
    )
    deleted = conn.execute("DELETE FROM practice.sessions WHERE id = %s", [theirs])
    assert (updated.rowcount, deleted.rowcount) == (0, 0)


def test_nothing_is_visible_without_a_learner(conn: Conn) -> None:
    a = add_user(conn)
    add_session(conn, a, add_content(conn, a))
    conn.execute("SET LOCAL ROLE listenup_api")

    assert conn.execute("SELECT count(*) FROM practice.sessions").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM practice.session_steps").fetchone() == (0,)


def test_a_learner_cannot_create_a_session_for_another_learner(
    conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _, content = owned
    conn.execute("RESET ROLE")
    other = add_user(conn)
    learner = owned[0]
    act_as_learner(conn, learner)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        add_session(conn, other, content)


def test_a_step_can_never_belong_to_another_learner(conn: Conn) -> None:
    # Even the owner role, which bypasses row-level security, cannot attach a step
    # of one learner to another learner's session: the key is (session_id, user_id).
    a, b = add_user(conn), add_user(conn)
    session = add_session(conn, a, add_content(conn, a), path=("dictation",))

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO practice.session_steps (session_id, user_id, step, position, status) "
            "VALUES (%s, %s, 'transcript', 2, 'locked')",
            [session, b],
        )


def test_a_step_cannot_move_to_another_learner(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    session = add_session(conn, a, add_content(conn, a))

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "UPDATE practice.session_steps SET user_id = %s WHERE session_id = %s", [b, session]
        )


def test_deleting_the_content_deletes_its_sessions_and_steps(conn: Conn) -> None:
    a = add_user(conn)
    content = add_content(conn, a)
    session = add_session(conn, a, content)

    conn.execute("DELETE FROM content.contents WHERE id = %s", [content])

    assert conn.execute(
        "SELECT count(*) FROM practice.session_steps WHERE session_id = %s", [session]
    ).fetchone() == (0,)


def test_updated_at_moves_on_every_change(conn: Conn, owned: tuple[uuid.UUID, uuid.UUID]) -> None:
    session = add_session(conn, *owned)
    conn.execute("RESET ROLE")
    # Age the row with the touch trigger off, so the change below is the one measured.
    conn.execute("ALTER TABLE practice.sessions DISABLE TRIGGER sessions_touch")
    conn.execute(
        "UPDATE practice.sessions SET updated_at = now() - interval '1 hour' WHERE id = %s",
        [session],
    )
    conn.execute("ALTER TABLE practice.sessions ENABLE TRIGGER sessions_touch")

    conn.execute("UPDATE practice.sessions SET version = version + 1 WHERE id = %s", [session])

    row = conn.execute(
        "SELECT updated_at > now() - interval '1 minute' FROM practice.sessions WHERE id = %s",
        [session],
    ).fetchone()
    assert row == (True,)


def test_a_session_can_only_practise_the_learners_own_content(conn: Conn) -> None:
    owner, other = add_user(conn), add_user(conn)
    their_clip = add_content(conn, owner)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_session(conn, other, their_clip)
