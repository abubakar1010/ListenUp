"""Content tables: reference counting, deletion and row-level security (migration 0005)."""

import uuid

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]


def add_user(conn: Conn) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO identity.users (id, email) VALUES (%s, %s)", [user_id, f"{user_id}@ex.com"]
    )
    return user_id


def add_upload(conn: Conn, owner: uuid.UUID) -> uuid.UUID:
    media_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by) "
        "VALUES (%s, %s, 'upload', %s)",
        [media_id, f"upload:{owner}:{media_id}", owner],
    )
    return media_id


def add_youtube(conn: Conn) -> uuid.UUID:
    media_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO content.media_objects (id, fingerprint, source, source_ref) "
        "VALUES (%s, %s, 'youtube', 'abc')",
        [media_id, f"youtube:{media_id}"],
    )
    return media_id


def add_content(conn: Conn, user_id: uuid.UUID, media_id: uuid.UUID) -> uuid.UUID:
    content_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO content.contents (id, user_id, media_object_id, title) "
        "VALUES (%s, %s, %s, 'Clip')",
        [content_id, user_id, media_id],
    )
    return content_id


def ref_count(conn: Conn, media_id: uuid.UUID) -> object:
    row = conn.execute(
        "SELECT ref_count FROM content.media_objects WHERE id = %s", [media_id]
    ).fetchone()
    return row[0] if row else None


def act_as_learner(conn: Conn, learner: uuid.UUID) -> None:
    conn.execute("SET LOCAL ROLE listenup_api")
    conn.execute("SELECT set_config('app.user_id', %s, true)", [str(learner)])


def test_content_items_count_references_to_shared_media(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    media = add_youtube(conn)

    first = add_content(conn, a, media)
    add_content(conn, b, media)
    assert ref_count(conn, media) == 2

    conn.execute("DELETE FROM content.contents WHERE id = %s", [first])
    assert ref_count(conn, media) == 1


def test_the_api_role_counts_references_too(conn: Conn) -> None:
    learner = add_user(conn)
    media = add_youtube(conn)
    act_as_learner(conn, learner)

    add_content(conn, learner, media)

    conn.execute("RESET ROLE")
    assert ref_count(conn, media) == 1


def test_media_in_use_cannot_be_deleted(conn: Conn) -> None:
    learner = add_user(conn)
    media = add_youtube(conn)
    add_content(conn, learner, media)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("DELETE FROM content.media_objects WHERE id = %s", [media])


def test_deleting_an_account_removes_its_uploads_and_releases_shared_media(conn: Conn) -> None:
    learner, other = add_user(conn), add_user(conn)
    upload = add_upload(conn, learner)
    shared = add_youtube(conn)
    add_content(conn, learner, upload)
    add_content(conn, learner, shared)
    add_content(conn, other, shared)

    conn.execute("DELETE FROM identity.users WHERE id = %s", [learner])

    assert ref_count(conn, upload) is None  # the upload went with the account
    assert ref_count(conn, shared) == 1  # the other learner still uses it


def test_the_same_clip_appears_once_per_library(conn: Conn) -> None:
    learner = add_user(conn)
    media = add_youtube(conn)
    add_content(conn, learner, media)

    with pytest.raises(psycopg.errors.UniqueViolation):
        add_content(conn, learner, media)


def test_an_upload_must_name_its_uploader(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO content.media_objects (id, fingerprint, source) "
            "VALUES (%s, 'upload:x', 'upload')",
            [uuid.uuid4()],
        )


def test_a_learner_sees_media_only_through_their_content_or_uploads(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    in_library = add_youtube(conn)
    not_in_library = add_youtube(conn)
    own_upload = add_upload(conn, a)
    other_upload = add_upload(conn, b)
    add_content(conn, a, in_library)
    act_as_learner(conn, a)

    visible = {row[0] for row in conn.execute("SELECT id FROM content.media_objects")}

    assert visible == {in_library, own_upload}
    assert not visible & {not_in_library, other_upload}


def test_the_api_may_create_only_the_learners_own_uploads(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    act_as_learner(conn, a)

    add_upload(conn, a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        add_upload(conn, b)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        add_youtube(conn)


def test_the_api_cannot_change_shared_media(conn: Conn) -> None:
    learner = add_user(conn)
    media = add_upload(conn, learner)
    act_as_learner(conn, learner)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE content.media_objects SET status = 'playable' WHERE id = %s", [media])


def test_a_learner_sees_only_their_own_content_items(conn: Conn) -> None:
    a, b = add_user(conn), add_user(conn)
    media = add_youtube(conn)
    mine = add_content(conn, a, media)
    add_content(conn, b, media)
    act_as_learner(conn, a)

    assert [row[0] for row in conn.execute("SELECT id FROM content.contents")] == [mine]
