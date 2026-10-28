"""Durable deletion and conversion-writer barriers (DR-2)."""

import uuid

import psycopg
import pytest


def test_content_deletion_schema_has_private_writer_barrier(conn: psycopg.Connection) -> None:
    assert conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='content' "
        "AND table_name='contents' AND column_name='deleting_at'"
    ).fetchone() == ("deleting_at",)
    assert conn.execute(
        "SELECT policyname FROM pg_policies WHERE schemaname='content' AND tablename='media_writes'"
    ).fetchall() == [("own_rows",)]
    assert conn.execute(
        "SELECT has_table_privilege('listenup_api','content.media_writes','SELECT'), "
        "has_table_privilege('listenup_api','content.media_writes','INSERT')"
    ).fetchone() == (True, False)


def test_media_writer_prevents_removing_its_media(conn: psycopg.Connection) -> None:
    learner, media, writer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(
        "INSERT INTO identity.users(id,email) VALUES (%s,%s)", (learner, f"{learner}@example.com")
    )
    conn.execute(
        "INSERT INTO content.media_objects(id,fingerprint,source,uploaded_by) "
        "VALUES (%s,%s,'upload',%s)",
        (media, str(media), learner),
    )
    conn.execute(
        "INSERT INTO content.media_writes(id,media_object_id,user_id,owner) VALUES (%s,%s,%s,%s)",
        (writer, media, learner, "test:1"),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("DELETE FROM content.media_objects WHERE id=%s", (media,))
