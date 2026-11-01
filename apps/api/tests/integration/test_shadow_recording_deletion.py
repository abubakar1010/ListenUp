"""FR-SH-17, NFR-SEC-5 (#90): a learner deletes one Shadow recording; the round stays."""

import functools

import psycopg
import pytest

from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import FakeStorage, client_factory
from tests.integration.test_shadow_recording import key_of, record_round, request_upload
from tests.integration.test_shadow_rounds import base, end_round, setup, start_round


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def make(api_role_url, migrated_url, storage):
    url = conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker"
    for factory in client_factory(api_role_url, storage):
        yield functools.partial(factory, transcript_read_database_url=url)


@pytest.fixture
def client(make):
    return make()


def delete_recording(client, round_id):
    return client.delete(f"/api/v1/shadow/rounds/{round_id}/recording")


def round_columns(url, round_id):
    with psycopg.connect(url) as db:
        return db.execute(
            "SELECT recording_key,recording_mime,recording_bytes,uploaded_at,recorded_at "
            "FROM practice.shadow_rounds WHERE id=%s",
            [round_id],
        ).fetchone()


def test_deleting_one_recording_removes_the_file_and_keeps_the_round_complete(
    client, migrated_url, api_role_url, storage
):
    """#90 criterion 2: the file goes, the round keeps `recorded_at` (so a later grade,
    keyed by the round, stays) and the completed Shadow step stays complete."""
    sid = setup(client, migrated_url, api_role_url)
    bodies = [record_round(client, storage, sid, n) for n in (1, 2, 3)]
    first, key = bodies[0]["round_id"], key_of(bodies[0]["upload"])
    session = client.get(f"/api/v1/sessions/{sid}").json()
    assert session["status"] == "completed"
    recorded_at = round_columns(migrated_url, first)[4]

    response = delete_recording(client, first)

    assert response.status_code == 204, response.text
    assert key in storage.deleted and key not in storage.objects
    assert round_columns(migrated_url, first) == (None, None, None, None, recorded_at)
    rounds = client.get(base(sid)).json()["rounds"]
    assert rounds[0]["recorded_at"] is not None
    assert rounds[0]["recording_available"] is False
    assert [r["recording_available"] for r in rounds[1:]] == [True, True]
    # The other recordings are untouched.
    assert {key_of(b["upload"]) for b in bodies[1:]} <= storage.objects.keys()
    assert client.get(f"/api/v1/sessions/{sid}").json() == session
    replay = client.get(f"/api/v1/shadow/rounds/{first}/recording", follow_redirects=False)
    assert (replay.status_code, replay.json()["code"]) == (409, "recording_not_ready")
    # Deleting again is harmless.
    assert delete_recording(client, first).status_code == 204
    assert client.get(f"/api/v1/sessions/{sid}").json() == session


def test_no_row_lock_is_held_while_the_file_is_deleted(
    client, migrated_url, api_role_url, storage, monkeypatch
):
    """Storage first, rows second, and never a storage call under a row lock (#249)."""
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    original, seen = storage.delete, []

    async def probe(key):
        with psycopg.connect(migrated_url, autocommit=True) as db:
            for table, row in (("shadow_rounds", body["round_id"]), ("sessions", sid)):
                db.execute(f"SELECT 1 FROM practice.{table} WHERE id=%s FOR UPDATE NOWAIT", [row])
            seen.append(round_columns(migrated_url, body["round_id"])[0])
        await original(key)

    monkeypatch.setattr(storage, "delete", probe)
    assert delete_recording(client, body["round_id"]).status_code == 204
    # The row still named the key while its file was being deleted.
    assert seen == [key_of(body["upload"])]


def test_a_failed_storage_delete_keeps_the_key_for_a_retry(
    client, migrated_url, api_role_url, storage, monkeypatch
):
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    original = storage.delete

    async def unavailable(key):
        raise OSError("storage unavailable")

    monkeypatch.setattr(storage, "delete", unavailable)
    assert delete_recording(client, body["round_id"]).status_code == 500
    assert round_columns(migrated_url, body["round_id"])[0] == key_of(body["upload"])
    monkeypatch.setattr(storage, "delete", original)
    assert delete_recording(client, body["round_id"]).status_code == 204
    assert round_columns(migrated_url, body["round_id"])[0] is None
    assert key_of(body["upload"]) not in storage.objects


def test_another_learner_gets_404_and_nothing_is_deleted(make, migrated_url, api_role_url, storage):
    owner = make()
    sid = setup(owner, migrated_url, api_role_url)
    body = record_round(owner, storage, sid, 1)
    response = delete_recording(make(), body["round_id"])
    assert (response.status_code, response.json()["code"]) == (404, "round_not_found")
    assert body["round_id"] not in response.text
    assert storage.deleted == []
    assert round_columns(migrated_url, body["round_id"])[0] == key_of(body["upload"])


def test_unrecorded_round_and_missing_csrf_are_refused(client, migrated_url, api_role_url, storage):
    sid = setup(client, migrated_url, api_role_url)
    start_round(client, sid, 1)
    end_round(client, sid, 1)
    upload = request_upload(client, sid, 1).json()
    storage.arrive(key_of(upload["upload"]), 200_000, "audio/webm")
    pending = delete_recording(client, upload["round_id"])
    assert (pending.status_code, pending.json()["code"]) == (409, "recording_not_ready")
    assert storage.deleted == []
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        refused = delete_recording(client, upload["round_id"])
    finally:
        client.headers["X-CSRF-Token"] = csrf
    assert refused.status_code == 403
    assert storage.deleted == []


def test_withdrawn_voice_consent_does_not_block_deleting_a_recording(
    client, migrated_url, api_role_url, storage
):
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    assert (
        client.post("/api/v1/me/consents/withdraw", json={"kind": "voice_recording"}).status_code
        == 200
    )
    assert delete_recording(client, body["round_id"]).status_code == 204
    assert key_of(body["upload"]) not in storage.objects


def test_a_recorded_round_accepts_only_clearing_the_whole_recording(
    client, migrated_url, api_role_url, storage
):
    """The `check_shadow_round` rule the learner's delete relies on (ADR 0092)."""
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    rid, key = body["round_id"], key_of(body["upload"])
    refused = (
        "UPDATE practice.shadow_rounds SET recording_key=NULL WHERE id=%s",
        "UPDATE practice.shadow_rounds SET recording_key=NULL,recording_mime=NULL,"
        "recording_bytes=NULL,uploaded_at=NULL,recorded_at=NULL WHERE id=%s",
        "UPDATE practice.shadow_rounds SET recording_key=NULL,recording_mime=NULL,"
        "recording_bytes=NULL,uploaded_at=NULL,recorded_at=now()+interval '1 s' WHERE id=%s",
    )
    with psycopg.connect(migrated_url, autocommit=True) as db:
        for statement in refused:
            with pytest.raises(psycopg.errors.CheckViolation):
                db.execute(statement, [rid])
    assert delete_recording(client, rid).status_code == 204
    with (
        psycopg.connect(migrated_url, autocommit=True) as db,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        # A deleted recording can never be restored onto the round.
        db.execute(
            "UPDATE practice.shadow_rounds SET recording_key=%s,recording_mime='audio/webm',"
            "recording_bytes=200000,uploaded_at=now() WHERE id=%s",
            [key, rid],
        )


def test_withdrawn_voice_consent_blocks_rounds_until_given_again(
    client, migrated_url, api_role_url, storage
):
    """#90 criterion 3 (FR-SH-17, built by #78/#81, ADRs 0069 and 0070)."""
    sid = setup(client, migrated_url, api_role_url)
    record_round(client, storage, sid, 1)
    withdrawn = client.post("/api/v1/me/consents/withdraw", json={"kind": "voice_recording"})
    assert withdrawn.status_code == 200
    for refused in (start_round(client, sid, 2), request_upload(client, sid, 1)):
        assert (refused.status_code, refused.json()["code"]) == (403, "voice_consent_required")
    assert len(client.get(base(sid)).json()["rounds"]) == 1
    version = client.get("/api/v1/auth/consent-versions").json()["voice_recording"]
    granted = client.post(
        "/api/v1/me/consents", json={"kind": "voice_recording", "version": version}
    )
    assert granted.status_code == 200
    record_round(client, storage, sid, 2)
    assert len(client.get(base(sid)).json()["rounds"]) == 2


def test_a_deleted_recording_is_audited_and_deleted_again_after_its_upload_link_expires(
    client, migrated_url, api_role_url, storage
):
    """Owner decision (review of #263): deleting one recording writes an
    `ops.deletion_requests` row (scope 'recordings'). After the signed upload URL has
    expired, the reconciler deletes the key once more, so a late retried PUT cannot
    leave voice data behind, and then completes the request."""
    import asyncio

    from listenup.modules.library import jobs
    from listenup.platform.database import Database
    from listenup.platform.jobs import JobDeps, run_handler
    from listenup.platform.storage import use_storage

    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    rid, key = body["round_id"], key_of(body["upload"])
    assert delete_recording(client, rid).status_code == 204
    assert delete_recording(client, rid).status_code == 204  # no second request
    ttl = client.app.state.settings.signed_url_ttl_seconds
    with psycopg.connect(migrated_url) as db:
        rows = db.execute(
            "SELECT id, status, report->'keys', due_at - requested_at "
            "FROM ops.deletion_requests WHERE scope='recordings' AND target_id=%s",
            [rid],
        ).fetchall()
    assert len(rows) == 1
    request, status, keys, delay = rows[0]
    assert (status, keys) == ("storage_deleted", [key])
    assert delay.total_seconds() >= ttl
    storage.arrive(key, 200_000, "audio/webm")  # a stale signed PUT lands late

    async def run(handler, **args):
        database = Database(conninfo_to_url(migrated_url))
        try:
            return await handler(database)
        finally:
            await database.dispose()

    def todo():
        with psycopg.connect(migrated_url) as db:
            return db.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
                "task_name='library.delete_recordings' AND args->>'request_id'=%s "
                "AND status='todo'",
                [str(request)],
            ).fetchone()[0]

    reconcile = lambda database: jobs.reconcile_content_deletions(JobDeps(database, None, 1))  # noqa: E731
    asyncio.run(run(reconcile))
    assert todo() == 0  # not before the upload link has expired
    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE ops.deletion_requests SET due_at=requested_at WHERE id=%s", [request])
    asyncio.run(run(reconcile))
    assert todo() == 1
    use_storage(storage)
    try:
        asyncio.run(
            run(
                lambda database: run_handler(
                    "library.delete_recordings", JobDeps(database, None, 1), request_id=str(request)
                )
            )
        )
    finally:
        use_storage(None)
    assert key not in storage.objects
    with psycopg.connect(migrated_url) as db:
        assert db.execute(
            "SELECT status FROM ops.deletion_requests WHERE id=%s", [request]
        ).fetchone() == ("completed",)
        db.execute(
            "DELETE FROM procrastinate.procrastinate_jobs WHERE args->>'request_id'=%s",
            [str(request)],
        )
    asyncio.run(run(reconcile))
    assert todo() == 0  # a completed recording deletion is not swept again


def recording_requests(url, round_id):
    with psycopg.connect(url) as db:
        return db.execute(
            "SELECT id, status FROM ops.deletion_requests WHERE scope='recordings' "
            "AND target_id=%s",
            [round_id],
        ).fetchall()


def test_a_delete_that_another_one_beat_writes_no_second_audit_row(
    client, migrated_url, api_role_url, storage, monkeypatch
):
    """Review of #263: when a concurrent delete (or retention) clears the round while
    this request deletes the file, only the request that cleared it audits the delete."""
    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    original = storage.delete

    async def raced(key):
        await original(key)
        with psycopg.connect(migrated_url, autocommit=True) as db:
            db.execute(
                "UPDATE practice.shadow_rounds SET recording_key=NULL, recording_mime=NULL, "
                "recording_bytes=NULL, uploaded_at=NULL WHERE id=%s",
                [body["round_id"]],
            )

    monkeypatch.setattr(storage, "delete", raced)
    assert delete_recording(client, body["round_id"]).status_code == 204
    assert recording_requests(migrated_url, body["round_id"]) == []


def test_a_recording_sweep_that_gave_up_is_retried_after_a_wait(
    client, migrated_url, api_role_url, storage
):
    """Review of #263: an exhausted `library.delete_recordings` marks its request failed;
    the reconciler retries it only after `RECORDINGS_RETRY_AFTER`, then completes it."""
    import asyncio

    from listenup.modules.library import jobs
    from listenup.platform.database import Database
    from listenup.platform.jobs import JobDeps, run_handler
    from listenup.platform.storage import use_storage

    sid = setup(client, migrated_url, api_role_url)
    body = record_round(client, storage, sid, 1)
    rid, key = body["round_id"], key_of(body["upload"])
    assert delete_recording(client, rid).status_code == 204
    [(request, _)] = recording_requests(migrated_url, rid)

    async def run(handler):
        database = Database(conninfo_to_url(migrated_url))
        try:
            return await handler(JobDeps(database, None, 1))
        finally:
            await database.dispose()

    def queued():
        with psycopg.connect(migrated_url) as db:
            return db.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE "
                "task_name='library.delete_recordings' AND args->>'request_id'=%s "
                "AND status='todo'",
                [str(request)],
            ).fetchone()[0]

    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE ops.deletion_requests SET due_at=requested_at WHERE id=%s", [request])
    asyncio.run(run(lambda deps: jobs.give_up_recordings(deps, str(request))))
    assert recording_requests(migrated_url, rid) == [(request, "failed")]
    asyncio.run(run(jobs.reconcile_content_deletions))
    assert queued() == 0  # not straight away
    with psycopg.connect(migrated_url) as db:
        db.execute(
            "UPDATE ops.deletion_requests SET failed_at = failed_at - %s WHERE id=%s",
            [jobs.RECORDINGS_RETRY_AFTER, request],
        )
    asyncio.run(run(jobs.reconcile_content_deletions))
    assert queued() == 1
    storage.arrive(key, 200_000, "audio/webm")
    use_storage(storage)
    try:
        asyncio.run(
            run(
                lambda deps: run_handler("library.delete_recordings", deps, request_id=str(request))
            )
        )
    finally:
        use_storage(None)
    assert key not in storage.objects
    assert recording_requests(migrated_url, rid) == [(request, "completed")]
    # A completed request makes the job a no-op.
    asyncio.run(
        run(lambda deps: run_handler("library.delete_recordings", deps, request_id=str(request)))
    )
