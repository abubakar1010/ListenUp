"""Correction writes cannot outlive an owned content parent (#56, ADR 0058)."""

import asyncio
import concurrent.futures
import threading
import time
import uuid

import psycopg
import pytest

from listenup.modules.content import service as content
from listenup.modules.transcript import repository
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from tests.integration.intake_helpers import learner_id
from tests.integration.test_dictation_disputes import (
    attempt,
    client,
    dispute,
    make_client,
    share_clip,
    storage,
)

__all__ = ["attempt", "client", "make_client", "storage"]


@pytest.mark.anyio
async def test_correction_parent_lock_refuses_another_learners_content(
    client, make_client, attempt, migrated_url, api_role_url
):
    other = make_client()
    with psycopg.connect(migrated_url) as conn:
        clip = conn.execute(
            "SELECT content_id FROM practice.sessions WHERE id=%s", [attempt["session_id"]]
        ).fetchone()[0]
    database = Database(api_role_url)
    try:
        async with database.transaction(uuid.UUID(learner_id(other))) as db:
            with pytest.raises(ProblemError) as refused:
                await content.retain_content(db, uuid.UUID(learner_id(other)), clip)
        assert (refused.value.status, refused.value.code) == (404, "content_not_found")
    finally:
        await database.dispose()


def test_content_deletion_waits_for_inflight_dispute_and_removes_its_correction(
    client, make_client, attempt, migrated_url, monkeypatch
):
    other = make_client()
    _, media = share_clip(client, other, attempt, migrated_url)
    user = learner_id(client)
    retained, release, deleting = threading.Event(), threading.Event(), threading.Event()
    writer_pid: list[int] = []
    original = repository.correct_word

    async def paused_write(*args, **kwargs):
        retained.set()  # correct_word has retained the content parent before this write
        assert await asyncio.to_thread(release.wait, 10)
        await original(*args, **kwargs)

    def delete_content():
        with psycopg.connect(migrated_url) as conn:
            writer_pid.append(conn.info.backend_pid)
            deleting.set()
            conn.execute(
                "DELETE FROM content.contents WHERE user_id=%s AND media_object_id=%s",
                [user, media],
            )

    monkeypatch.setattr(repository, "correct_word", paused_write)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        correction = pool.submit(dispute, client, attempt["id"])
        try:
            assert retained.wait(5)
            deletion = pool.submit(delete_content)
            assert deleting.wait(5)
            with psycopg.connect(migrated_url, autocommit=True) as observer:
                deadline = time.monotonic() + 5
                while not observer.execute(
                    "SELECT pg_blocking_pids(%s)", [writer_pid[0]]
                ).fetchone()[0]:
                    assert time.monotonic() < deadline, "deletion must wait for the dispute"
                    if deletion.done():
                        deletion.result()
                        pytest.fail("deletion passed the in-flight correction")
        finally:
            release.set()
        response = correction.result(timeout=10)
        assert response.status_code == 200, response.text
        deletion.result(timeout=10)
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM content.transcript_corrections WHERE user_id=%s", [user]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT words FROM content.passage_transcripts WHERE media_object_id=%s", [media]
        ).fetchall() == [(["cat"],)]
