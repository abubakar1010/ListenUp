"""Delete an account and restore it within the grace period (#91, #120; D9; ADR 0029).

The app connects as a role with only the API's rights, so row-level security is in
force as in production. Emails go to an in-memory outbox and stored files to the fake
storage; the purge job runs either through a real Procrastinate worker (`deliver`) or
by calling its handler directly, where a test needs its return value.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Response
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

from listenup.main import create_app
from listenup.modules.identity import jobs as identity_jobs
from listenup.modules.identity import repository as identity_repository
from listenup.modules.identity.domain.tokens import new_token, token_hash
from listenup.modules.identity.service import build_accounts
from listenup.modules.notifications import service as notifications
from listenup.platform import jobs as platform_jobs
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import JobDeps, run_handler
from listenup.platform.rate_limit import RateLimiter
from listenup.platform.storage import StoredObject, use_storage
from tests.integration.conftest import conninfo_to_url, with_csrf
from tests.integration.intake_helpers import FakeStorage
from tests.integration.seed import SeededLearner, seed_learner_data
from tests.integration.test_password_reset import Outbox, deliver

PASSWORD = "correct horse battery"
GRACE = timedelta(days=7)
STORED = StoredObject(10, "audio/mp4")

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def outbox(migrated_url: str) -> Iterator[Outbox]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    box = Outbox()
    notifications.use_transport(box)
    yield box
    notifications.use_transport(None)


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, outbox: Outbox, storage: FakeStorage) -> Iterator[ClientFactory]:
    opened: list[TestClient] = []

    def make(**settings: object) -> TestClient:
        app_ = create_app(Settings(database_url=api_role_url, log_json=False, **settings))  # type: ignore[arg-type]
        client = TestClient(app_, raise_server_exceptions=False, client=("203.0.113.7", 50000))
        client.__enter__()
        opened.append(client)
        return with_csrf(client)

    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def unique_email() -> str:
    return f"delete-{uuid.uuid4().hex}@example.com"


def register(client: TestClient, email: str) -> uuid.UUID:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


def login(client: TestClient, email: str, *, restore: bool | None = None) -> Response:
    body: dict[str, object] = {"email": email, "password": PASSWORD}
    if restore is not None:
        body["restore"] = restore
    return client.post("/api/v1/auth/login", json=body)


def delete_me(client: TestClient, password: str = PASSWORD, confirm: object = True) -> Response:
    return client.request("DELETE", "/api/v1/me", json={"password": password, "confirm": confirm})


def user_row(migrated_url: str, user_id: uuid.UUID) -> tuple[Any, ...] | None:
    with psycopg.connect(migrated_url) as conn:
        return conn.execute(
            "SELECT status, deletion_scheduled_at FROM identity.users WHERE id = %s", [user_id]
        ).fetchone()


def deletion_request(migrated_url: str, user_id: uuid.UUID) -> dict[str, Any]:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT id, status, storage_prefixes, media_object_ids, due_at, requested_at, "
            "cancelled_at, completed_at, report FROM ops.deletion_requests "
            "WHERE subject_user_id = %s ORDER BY requested_at DESC LIMIT 1",
            [user_id],
        ).fetchone()
    assert row is not None, "no deletion request"
    keys = [
        "id",
        "status",
        "storage_prefixes",
        "media_object_ids",
        "due_at",
        "requested_at",
        "cancelled_at",
        "completed_at",
        "report",
    ]
    return dict(zip(keys, row, strict=True))


def learner_rows(migrated_url: str, user_id: uuid.UUID) -> int:
    """Rows of the learner in every table with a user_id or uploaded_by column."""
    with psycopg.connect(migrated_url) as conn:
        columns = conn.execute(
            "SELECT c.table_schema, c.table_name, c.column_name "
            "FROM information_schema.columns c JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE t.table_type = 'BASE TABLE' AND c.column_name IN ('user_id', 'uploaded_by') "
            "  AND c.table_schema IN ('identity', 'content', 'practice', 'grading', 'ops')"
        ).fetchall()
        total = 0
        for schema, table, column in columns:
            row = conn.execute(
                f'SELECT count(*) FROM "{schema}"."{table}" WHERE "{column}" = %s',  # type: ignore[arg-type]
                [user_id],
            ).fetchone()
            assert row is not None
            total += int(row[0])
        return total


def make_due(migrated_url: str, user_id: uuid.UUID, ago: timedelta = timedelta(days=1)) -> None:
    """Move the deletion's dates back as if it had been asked for over 7 days ago."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.deletion_requests SET requested_at = now() - %s - interval '7 days', "
            "due_at = now() - %s WHERE subject_user_id = %s",
            [ago, ago, user_id],
        )
        conn.execute(
            "UPDATE identity.users SET deletion_scheduled_at = now() - %s "
            "WHERE id = %s AND status = 'pending_deletion'",
            [ago, user_id],
        )


def run_job(migrated_url: str, handler: Callable[..., Any], **args: Any) -> Any:
    async def run() -> Any:
        database = Database(conninfo_to_url(migrated_url), pool_size=2)
        try:
            return await handler(JobDeps(database, None, 1), **args)
        finally:
            await database.dispose()

    return asyncio.run(run())


def sweep_queues_purge(migrated_url: str, user_id: uuid.UUID) -> bool:
    """Run the scheduled sweep; True when it left a purge of this learner's request queued.

    Other tests' requests share the database, so the sweep's own count says little.
    """
    run_job(migrated_url, identity_jobs.purge_due_accounts)
    request_id = str(deletion_request(migrated_url, user_id)["id"])
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s AND status = 'todo' AND args->>'request_id' = %s",
            [identity_jobs.PURGE_ACCOUNT, request_id],
        ).fetchone()
    assert row is not None
    return bool(row[0])


def signed_in_learner_with_data(
    client: TestClient, migrated_url: str
) -> tuple[str, uuid.UUID, SeededLearner]:
    email = unique_email()
    user_id = register(client, email)
    return email, user_id, seed_learner_data(migrated_url, user_id)


def add_shared_youtube(migrated_url: str, *learners: uuid.UUID) -> uuid.UUID:
    media_id = uuid.uuid4()
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "INSERT INTO content.media_objects (id, fingerprint, source, source_ref, status) "
            "VALUES (%s, %s, 'youtube', 'abc', 'playable')",
            [media_id, f"youtube:{media_id}"],
        )
        for learner in learners:
            conn.execute(
                "INSERT INTO content.contents (id, user_id, media_object_id, title) "
                "VALUES (%s, %s, %s, 'Shared clip')",
                [uuid.uuid4(), learner, media_id],
            )
    return media_id


def ref_count(migrated_url: str, media_id: uuid.UUID) -> int | None:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT ref_count FROM content.media_objects WHERE id = %s", [media_id]
        ).fetchone()
    return None if row is None else int(row[0])


# -- deleting (#91) ----------------------------------------------------------------------


def test_deleting_disables_the_account_at_once_and_keeps_the_data(
    make_client: ClientFactory, migrated_url: str
) -> None:
    phone, laptop = make_client(), make_client()
    email, user_id, _ = signed_in_learner_with_data(phone, migrated_url)
    assert login(laptop, email).status_code == 200
    rows_before = learner_rows(migrated_url, user_id)

    response = delete_me(phone)

    assert response.status_code == 202
    until = datetime.fromisoformat(response.json()["deletion_scheduled_at"])
    assert GRACE - timedelta(minutes=1) < until - datetime.now(UTC) <= GRACE
    # Both devices are signed out at once, and the account counts as disabled.
    for device in (phone, laptop):
        me = device.get("/api/v1/me")
        assert (me.status_code, me.json()["code"]) == (401, "not_signed_in")
        assert device.get("/api/v1/library/contents").status_code == 401
    assert user_row(migrated_url, user_id) == ("pending_deletion", until)
    request = deletion_request(migrated_url, user_id)
    assert request["status"] == "pending"
    assert request["storage_prefixes"] == [f"users/{user_id}/"]
    assert request["media_object_ids"] == []  # the purge records them when it runs
    assert request["due_at"] == until
    # Within the grace period nothing is gone yet (only the login sessions).
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM identity.auth_sessions WHERE user_id = %s", [user_id]
        ).fetchone()
    assert row == (0,)
    assert learner_rows(migrated_url, user_id) == rows_before - 2  # the two login sessions


def test_deleting_needs_the_current_password(make_client: ClientFactory, migrated_url: str) -> None:
    client = make_client()
    user_id = register(client, unique_email())

    wrong = delete_me(client, password="not my password")

    assert (wrong.status_code, wrong.json()["code"]) == (403, "wrong_password")
    assert client.get("/api/v1/me").status_code == 200
    assert user_row(migrated_url, user_id) == ("active", None)


def test_wrong_passwords_count_towards_the_sign_in_lockout(make_client: ClientFactory) -> None:
    client = make_client(login_lock_threshold=2)
    register(client, unique_email())

    first = delete_me(client, password="guess one")
    second = delete_me(client, password="guess two")

    assert first.json()["code"] == "wrong_password"
    assert (second.status_code, second.json()["code"]) == (429, "account_locked")
    assert delete_me(client).json()["code"] == "account_locked"


def test_deleting_needs_an_explicit_confirmation(client: TestClient, migrated_url: str) -> None:
    user_id = register(client, unique_email())

    for confirm in (False, None, "yes"):
        response = delete_me(client, confirm=confirm)
        assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert user_row(migrated_url, user_id) == ("active", None)


def test_deleting_needs_a_signed_in_learner(client: TestClient) -> None:
    response = delete_me(client)

    assert (response.status_code, response.json()["code"]) == (401, "not_signed_in")


def test_an_account_without_a_password_cannot_confirm_yet(
    client: TestClient, migrated_url: str
) -> None:
    """Google sign-in (#32) is not built: such accounts get a clear refusal."""
    user_id = uuid.uuid4()
    token = new_token()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.users (id, email) VALUES (%s, %s)",
            [user_id, unique_email()],
        )
        conn.execute(
            "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s, now() + interval '1 day')",
            [uuid.uuid4(), user_id, token_hash(token)],
        )
    client.cookies.set("listenup_session", token)

    response = delete_me(client, password="")

    assert (response.status_code, response.json()["code"]) == (409, "reauthentication_unavailable")
    assert user_row(migrated_url, user_id) == ("active", None)


def test_a_login_session_of_a_disabled_account_reaches_nothing(
    client: TestClient, migrated_url: str
) -> None:
    """Even a session row that outlived the deletion resolves to nobody."""
    email = unique_email()
    user_id = register(client, email)
    assert delete_me(client).status_code == 202
    token = new_token()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s, now() + interval '1 day')",
            [uuid.uuid4(), user_id, token_hash(token)],
        )
    client.cookies.set("listenup_session", token)

    for path in ("/api/v1/me", "/api/v1/library/contents", "/api/v1/sessions", "/api/v1/events"):
        response = client.get(path)
        assert (response.status_code, response.json()["code"]) == (401, "not_signed_in"), path
    # No new copy of the data either (ADR 0030).
    export = client.post("/api/v1/me/exports")
    assert (export.status_code, export.json()["code"]) == (401, "not_signed_in")
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM ops.data_exports WHERE user_id = %s", [user_id]
        ).fetchone() == (0,)


def test_a_reset_link_issued_before_the_deletion_stops_working(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = unique_email()
    register(client, email)
    assert client.post("/api/v1/auth/password-reset", json={"email": email}).status_code == 202
    deliver(migrated_url)
    [token] = outbox.tokens()

    assert delete_me(client).status_code == 202
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "a brand new passphrase"},
    )

    assert (response.status_code, response.json()["code"]) == (400, "invalid_reset_link")


def test_a_reset_asked_for_before_the_deletion_sends_no_link(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    """The email job had not run yet when the learner deleted the account."""
    email = unique_email()
    register(client, email)
    assert client.post("/api/v1/auth/password-reset", json={"email": email}).status_code == 202

    assert delete_me(client).status_code == 202
    deliver(migrated_url)

    assert outbox.tokens() == []
    assert [
        mail.subject.startswith("Your ListenUp account will be deleted") for mail in outbox.sent
    ] == [True]


def test_the_confirmation_email_says_how_to_restore(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = unique_email()
    register(client, email)
    until = datetime.fromisoformat(delete_me(client).json()["deletion_scheduled_at"])

    with psycopg.connect(migrated_url) as conn:
        [(args,)] = conn.execute(
            "SELECT args FROM procrastinate.procrastinate_jobs WHERE task_name = %s",
            [identity_jobs.SEND_DELETION_NOTICE],
        ).fetchall()
    assert set(args) <= {"user_id", "_request_id"}
    deliver(migrated_url)

    [mail] = outbox.sent
    assert mail.to == email
    day = f"{until.astimezone(UTC).day} {until.astimezone(UTC):%B %Y}"
    assert mail.subject == f"Your ListenUp account will be deleted on {day}"
    for part in (mail.text, mail.html):
        assert "Sign in" in part or "sign in" in part.lower()
        assert "http://localhost:5173/sign-in" in part
        assert f"{day}, {until.astimezone(UTC):%H:%M} UTC" in part


def test_no_email_when_the_account_was_restored_first(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = unique_email()
    register(client, email)
    delete_me(client)
    assert login(client, email, restore=True).status_code == 200

    deliver(migrated_url)

    assert outbox.sent == []


# -- restoring (#120) --------------------------------------------------------------------


def test_signing_in_asks_before_restoring(client: TestClient, migrated_url: str) -> None:
    email = unique_email()
    user_id = register(client, email)
    until = delete_me(client).json()["deletion_scheduled_at"]

    response = login(client, email)

    assert response.status_code == 409
    assert response.json()["code"] == "account_pending_deletion"
    assert datetime.fromisoformat(response.json()["deletion_scheduled_at"]) == (
        datetime.fromisoformat(until)
    )
    # Nothing changed: no login session, still scheduled. Declining is just this.
    assert client.get("/api/v1/me").status_code == 401
    assert user_row(migrated_url, user_id)[0] == "pending_deletion"  # type: ignore[index]
    assert deletion_request(migrated_url, user_id)["status"] == "pending"


def test_the_grace_period_shown_is_the_one_applied(make_client: ClientFactory) -> None:
    client = make_client(account_deletion_grace_days=3)
    register(client, unique_email())

    assert client.get("/api/v1/me").json()["deletion_grace_days"] == 3
    until = datetime.fromisoformat(delete_me(client).json()["deletion_scheduled_at"])
    assert timedelta(days=3) - timedelta(minutes=1) < until - datetime.now(UTC) <= timedelta(days=3)


def test_an_outdated_password_hash_is_renewed_only_once_signed_in(
    client: TestClient, migrated_url: str
) -> None:
    """The renewal comes after the restore step, which locks the deletion request
    before the users row as the purge does; a refused sign-in renews nothing."""
    email = unique_email()
    user_id = register(client, email)
    delete_me(client)
    outdated = PasswordHasher(time_cost=1).hash(PASSWORD)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET password_hash = %s WHERE id = %s", [outdated, user_id]
        )

    def stored_hash() -> str:
        with psycopg.connect(migrated_url) as conn:
            row = conn.execute(
                "SELECT password_hash FROM identity.users WHERE id = %s", [user_id]
            ).fetchone()
        assert row is not None
        return str(row[0])

    assert login(client, email).status_code == 409
    assert stored_hash() == outdated
    assert login(client, email, restore=True).status_code == 200
    assert stored_hash() != outdated
    assert login(client, email).status_code == 200  # the new hash works


def test_a_wrong_password_never_reveals_the_deletion(client: TestClient) -> None:
    email = unique_email()
    register(client, email)
    delete_me(client)

    response = client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})

    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")
    assert "deletion_scheduled_at" not in response.json()


def test_confirming_restores_the_account_with_all_its_data(
    client: TestClient, migrated_url: str
) -> None:
    email, user_id, world = signed_in_learner_with_data(client, migrated_url)
    rows_before = learner_rows(migrated_url, user_id)
    delete_me(client)
    # Restored three days into the grace period.
    make_due(migrated_url, user_id, ago=timedelta(days=-4))

    response = login(client, email, restore=True)

    assert response.status_code == 200
    assert response.json()["id"] == str(user_id)
    assert user_row(migrated_url, user_id) == ("active", None)
    request = deletion_request(migrated_url, user_id)
    assert request["status"] == "cancelled"
    assert request["cancelled_at"] is not None
    library = client.get("/api/v1/library/contents")
    assert library.status_code == 200
    assert str(world.content_id) in library.text
    assert client.get(f"/api/v1/sessions/{world.sessions['dictation']}").status_code == 200
    # The login session that deleting ended is replaced by the new one.
    assert learner_rows(migrated_url, user_id) == rows_before


def test_a_restored_account_is_never_purged(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    email, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    storage.objects[f"users/{user_id}/media/x/playback.mp4"] = STORED
    delete_me(client)
    login(client, email, restore=True)
    make_due(migrated_url, user_id)

    assert not sweep_queues_purge(migrated_url, user_id)
    request_id = deletion_request(migrated_url, user_id)["id"]
    assert run_job(migrated_url, identity_jobs.purge_account, request_id=str(request_id)) is None

    assert user_row(migrated_url, user_id) == ("active", None)
    assert f"users/{user_id}/media/x/playback.mp4" in storage.objects


def test_after_the_grace_period_sign_in_fails_as_for_an_unknown_account(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = unique_email()
    user_id = register(client, email)
    delete_me(client)
    make_due(migrated_url, user_id)

    for restore in (None, True):
        response = login(client, email, restore=restore)
        assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")
        assert "The email or password is wrong" in response.json()["detail"]
    assert client.post("/api/v1/auth/password-reset", json={"email": email}).status_code == 202
    deliver(migrated_url)
    assert outbox.sent == []  # no reset email for an account past its grace period
    assert user_row(migrated_url, user_id)[0] == "pending_deletion"  # type: ignore[index]


def test_a_password_reset_during_the_grace_period_still_needs_the_restore(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = unique_email()
    user_id = register(client, email)
    delete_me(client)
    client.post("/api/v1/auth/password-reset", json={"email": email})
    deliver(migrated_url)
    token = outbox.tokens()[-1]

    reset = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "a brand new passphrase"},
    )

    assert reset.status_code == 204
    assert client.get("/api/v1/me").status_code == 401
    assert user_row(migrated_url, user_id)[0] == "pending_deletion"  # type: ignore[index]
    again = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "a brand new passphrase"}
    )
    assert again.json()["code"] == "account_pending_deletion"


def test_a_reset_asked_for_during_the_grace_period_is_not_swallowed_by_an_older_one(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    """A reset job from before the deletion is still waiting when the learner asks again."""
    email = unique_email()
    register(client, email)
    assert client.post("/api/v1/auth/password-reset", json={"email": email}).status_code == 202
    assert delete_me(client).status_code == 202
    assert client.post("/api/v1/auth/password-reset", json={"email": email}).status_code == 202

    deliver(migrated_url)

    assert len(outbox.tokens()) == 1  # the older job sends nothing; the new one does


def test_an_email_past_its_grace_period_can_register_again_before_the_purge(
    client: TestClient, make_client: ClientFactory, migrated_url: str
) -> None:
    email = unique_email()
    old_id = register(client, email)
    delete_me(client)
    make_due(migrated_url, old_id)

    fresh = make_client()
    response = fresh.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert new_id != old_id
    assert login(fresh, email).json()["id"] == str(new_id)
    assert user_row(migrated_url, old_id) is not None  # still waits for its purge
    # While the grace period runs, the email stays taken.
    other = unique_email()
    pending_id = register(make_client(), other)
    delete_me_client = make_client()
    assert login(delete_me_client, other).status_code == 200
    assert delete_me(delete_me_client).status_code == 202
    taken = make_client().post("/api/v1/auth/register", json={"email": other, "password": PASSWORD})
    assert taken.json()["code"] == "email_taken"
    assert user_row(migrated_url, pending_id) is not None


def test_the_purge_removes_every_rate_counter_of_the_learner(
    client: TestClient, migrated_url: str
) -> None:
    """Counters have no foreign key to the learner, so the cascade misses them (DR-1)."""
    email = unique_email()
    user_id = register(client, email)
    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "not the one"})
    assert wrong.status_code == 401
    delete_me(client)
    make_due(migrated_url, user_id)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        # As uploading and adding audio leave them (user_key, daily_audio_key).
        for key in (f"upload:user:{user_id}", f"intake:user:{user_id}"):
            conn.execute(
                "INSERT INTO ops.rate_counters (key, window_start, count) VALUES (%s, now(), 1)",
                [key],
            )
        before = conn.execute(
            "SELECT count(*) FROM ops.rate_counters WHERE key LIKE %s", [f"%:user:{user_id}"]
        ).fetchone()
    assert before is not None and before[0] >= 3

    request_id = str(deletion_request(migrated_url, user_id)["id"])
    report = run_job(migrated_url, identity_jobs.purge_account, request_id=request_id)

    with psycopg.connect(migrated_url) as conn:
        after = conn.execute(
            "SELECT count(*) FROM ops.rate_counters WHERE key LIKE %s", [f"%{user_id}%"]
        ).fetchone()
    assert after == (0,)
    assert report["rows_removed"]["ops.rate_counters"] == before[0]


# -- the purge job (#91) -----------------------------------------------------------------


def test_nothing_is_purged_within_the_grace_period(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    _, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    key = f"users/{user_id}/media/m/playback.mp4"
    storage.objects[key] = STORED
    delete_me(client)
    rows = learner_rows(migrated_url, user_id)

    assert not sweep_queues_purge(migrated_url, user_id)
    request_id = deletion_request(migrated_url, user_id)["id"]
    assert run_job(migrated_url, identity_jobs.purge_account, request_id=str(request_id)) is None

    assert learner_rows(migrated_url, user_id) == rows
    assert key in storage.objects
    assert deletion_request(migrated_url, user_id)["status"] == "pending"


def test_the_purge_removes_everything_after_the_grace_period(
    make_client: ClientFactory, migrated_url: str, storage: FakeStorage, outbox: Outbox
) -> None:
    client, other_client = make_client(), make_client()
    email, user_id, world = signed_in_learner_with_data(client, migrated_url)
    other = register(other_client, unique_email())
    shared = add_shared_youtube(migrated_url, user_id, other)
    mine = [
        f"users/{user_id}/media/{world.media_id}/playback.mp4",
        f"users/{user_id}/media/{world.media_id}/peaks.json",
        f"users/{user_id}/uploads/{world.confirmed_upload_id}.mp3",
    ]
    only_mine = add_shared_youtube(migrated_url, user_id)
    export_id = uuid.uuid4()
    archive = f"users/{user_id}/exports/{export_id}.zip"
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ops.data_exports (id, user_id, status, archive_key, ready_at, "
            "expires_at) VALUES (%s, %s, 'ready', %s, now(), now() + interval '7 days')",
            [export_id, user_id, archive],
        )
    mine.append(archive)
    with psycopg.connect(migrated_url) as conn:
        exports = conn.execute(
            "SELECT count(*) FROM ops.data_exports WHERE user_id = %s", [user_id]
        ).fetchone()
    theirs = f"users/{other}/uploads/kept.mp3"
    shared_files = f"media/youtube/{shared}/playback.mp4"
    for key in [*mine, theirs, shared_files]:
        storage.objects[key] = STORED
    rows = learner_rows(migrated_url, user_id)
    delete_me(client)
    make_due(migrated_url, user_id)

    # Through a real worker: the sweep queues the purge, which then runs.
    assert sweep_queues_purge(migrated_url, user_id)
    deliver(migrated_url)

    assert user_row(migrated_url, user_id) is None
    assert learner_rows(migrated_url, user_id) == 0
    assert not [key for key in storage.objects if key.startswith(f"users/{user_id}/")]
    assert theirs in storage.objects and shared_files in storage.objects
    assert ref_count(migrated_url, shared) == 1  # the other learner still uses it
    # Unused shared media waits for the orphan clean-up (#89), not for this purge.
    assert ref_count(migrated_url, only_mine) == 0
    assert ref_count(migrated_url, world.media_id) is None
    request = deletion_request(migrated_url, user_id)
    assert request["status"] == "completed"
    assert request["completed_at"] is not None
    report = request["report"]
    assert report["objects_removed"] == len(mine)
    # Every row of the learner, minus the login session that deleting ended, plus the
    # account row itself (learner_rows counts only tables with a user_id).
    assert report["rows_total"] == rows - 1 + 1
    assert report["rows_removed"]["identity.users"] == 1
    assert report["rows_removed"]["content.contents"] == 3
    assert exports is not None and report["rows_removed"]["ops.data_exports"] == exports[0]
    assert request["media_object_ids"] == [world.media_id]
    assert login(client, email).json()["code"] == "invalid_credentials"
    assert login(client, email, restore=True).json()["code"] == "invalid_credentials"
    assert other_client.get("/api/v1/library/contents").status_code == 200


def test_the_purge_is_safe_to_run_again(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    _, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    storage.objects[f"users/{user_id}/a.bin"] = STORED
    delete_me(client)
    make_due(migrated_url, user_id)
    request_id = str(deletion_request(migrated_url, user_id)["id"])

    first = run_job(migrated_url, identity_jobs.purge_account, request_id=request_id)
    again = run_job(migrated_url, identity_jobs.purge_account, request_id=request_id)

    assert first is not None and first["objects_removed"] == 1
    assert again is None
    assert not sweep_queues_purge(migrated_url, user_id)
    assert deletion_request(migrated_url, user_id)["report"] == first


def test_the_purge_finishes_after_stopping_between_storage_and_rows(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    """A crash after the storage step: the next run deletes the rows and completes."""
    _, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    delete_me(client)
    make_due(migrated_url, user_id)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.deletion_requests SET status = 'storage_deleted', "
            "report = '{\"objects_removed\": 4}' WHERE subject_user_id = %s",
            [user_id],
        )
        conn.execute(
            "UPDATE identity.users SET status = 'deleting', deletion_scheduled_at = NULL "
            "WHERE id = %s",
            [user_id],
        )

    assert sweep_queues_purge(migrated_url, user_id)
    request_id = str(deletion_request(migrated_url, user_id)["id"])
    report = run_job(migrated_url, identity_jobs.purge_account, request_id=request_id)

    assert report is not None and report["objects_removed"] == 4
    assert user_row(migrated_url, user_id) is None
    assert deletion_request(migrated_url, user_id)["status"] == "completed"


def test_a_purge_still_running_is_not_queued_again_and_a_dead_one_resumes(
    client: TestClient, migrated_url: str
) -> None:
    """A purge outlasting the sweep interval is not queued behind itself, whose retry
    could then not go back to the queue; one whose worker died runs again."""
    _, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    delete_me(client)
    make_due(migrated_url, user_id)
    assert sweep_queues_purge(migrated_url, user_id)
    request_id = str(deletion_request(migrated_url, user_id)["id"])
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        # Taken by a worker that has since died (no worker row, no heartbeat).
        conn.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status = 'doing', worker_id = NULL "
            "WHERE task_name = %s AND args->>'request_id' = %s",
            [identity_jobs.PURGE_ACCOUNT, request_id],
        )

    assert not sweep_queues_purge(migrated_url, user_id)
    assert run_job(migrated_url, platform_jobs.recover_stalled_jobs) >= 1
    deliver(migrated_url)

    assert user_row(migrated_url, user_id) is None
    assert deletion_request(migrated_url, user_id)["status"] == "completed"


def run_purge_attempt(migrated_url: str, request_id: str, attempt: int) -> None:
    """One worker attempt of the purge: under its timeout, settled on the last one."""

    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=2)
        try:
            await run_handler(
                identity_jobs.PURGE_ACCOUNT, JobDeps(database, None, attempt), request_id=request_id
            )
        finally:
            await database.dispose()

    asyncio.run(run())


def test_a_purge_that_gives_up_is_marked_failed_and_retried_later(
    client: TestClient,
    migrated_url: str,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out last attempt leaves a visible 'failed' request, never a silent half."""
    email, user_id, _ = signed_in_learner_with_data(client, migrated_url)
    storage.objects[f"users/{user_id}/a.bin"] = STORED
    delete_me(client)
    make_due(migrated_url, user_id)
    request_id = str(deletion_request(migrated_url, user_id)["id"])
    entry = platform_jobs._registry[identity_jobs.PURGE_ACCOUNT]
    short = dataclasses.replace(entry.spec, timeout=timedelta(seconds=0.2))
    monkeypatch.setitem(
        platform_jobs._registry,
        identity_jobs.PURGE_ACCOUNT,
        dataclasses.replace(entry, spec=short),
    )

    class Broken(FakeStorage):
        async def delete_prefix(self, prefix: str) -> int:
            raise RuntimeError("storage is down")

    class Stalled(FakeStorage):
        async def delete_prefix(self, prefix: str) -> int:
            await asyncio.sleep(60)
            return 0

    use_storage(Broken())
    with pytest.raises(RuntimeError):
        run_purge_attempt(migrated_url, request_id, attempt=1)
    assert (
        deletion_request(migrated_url, user_id)["status"] == "pending"
    )  # retried by Procrastinate

    use_storage(Stalled())
    with pytest.raises(TimeoutError):
        run_purge_attempt(migrated_url, request_id, attempt=identity_jobs.PURGE_ATTEMPTS)

    request = deletion_request(migrated_url, user_id)
    assert request["status"] == "failed"
    assert request["report"]["failures"] == 1
    assert request["report"]["failed_step"] == "pending"
    # Half done is still disabled: no sign-in, no restore, and the sweep waits an hour.
    assert user_row(migrated_url, user_id) == ("deleting", None)
    assert login(client, email, restore=True).json()["code"] == "invalid_credentials"
    assert not sweep_queues_purge(migrated_url, user_id)

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.deletion_requests SET failed_at = now() - interval '61 minutes' "
            "WHERE id = %s",
            [request_id],
        )
    assert sweep_queues_purge(migrated_url, user_id)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s AND args->>'request_id' = %s",
            [identity_jobs.PURGE_ACCOUNT, request_id],
        )

    # Giving up again is recorded too: the count grows and the hour starts over.
    use_storage(Broken())
    with pytest.raises(RuntimeError):
        run_purge_attempt(migrated_url, request_id, attempt=identity_jobs.PURGE_ATTEMPTS)
    request = deletion_request(migrated_url, user_id)
    assert request["status"] == "failed"
    assert request["report"]["failures"] == 2
    assert request["report"]["failed_step"] == "pending"
    assert not sweep_queues_purge(migrated_url, user_id)

    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.deletion_requests SET failed_at = now() - interval '61 minutes' "
            "WHERE id = %s",
            [request_id],
        )
    use_storage(storage)
    report = run_job(migrated_url, identity_jobs.purge_account, request_id=request_id)

    assert report is not None and report["objects_removed"] == 1 and report["failures"] == 2
    assert user_row(migrated_url, user_id) is None
    finished = deletion_request(migrated_url, user_id)
    assert finished["status"] == "completed"
    assert learner_rows(migrated_url, user_id) == 0


def test_every_sign_in_method_asks_before_restoring(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    """Google sign-in (#32) is not built. When it is, its callback must end in
    `Accounts.complete_sign_in`, like the password sign-in; this checks that seam with
    an account that has no password, as a Google account will."""
    email = unique_email()
    user_id = register(client, email)
    delete_me(client)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE identity.users SET password_hash = NULL WHERE id = %s", [user_id])
    scope = {"type": "http", "headers": [], "client": ("203.0.113.7", 50000)}

    async def sign_in(restore: bool) -> StarletteResponse:
        database = Database(api_role_url, pool_size=1)
        accounts = build_accounts(
            database,
            RateLimiter(database),
            Settings(database_url=api_role_url, log_json=False),  # type: ignore[arg-type]
        )
        response = StarletteResponse()
        try:
            async with database.transaction() as session:
                account = await identity_repository.find_account(session, email)
                assert account is not None and account.password_hash is None
                await accounts.complete_sign_in(
                    session, Request(scope), response, account, restore=restore
                )
        finally:
            await database.dispose()
        return response

    with pytest.raises(ProblemError) as declined:
        asyncio.run(sign_in(restore=False))
    assert (declined.value.status, declined.value.code) == (409, "account_pending_deletion")
    assert deletion_request(migrated_url, user_id)["status"] == "pending"

    response = asyncio.run(sign_in(restore=True))

    assert "listenup_session=" in response.headers["set-cookie"]
    assert user_row(migrated_url, user_id) == ("active", None)
    assert deletion_request(migrated_url, user_id)["status"] == "cancelled"


def test_the_purge_never_deletes_an_active_account(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    user_id = register(client, unique_email())
    storage.objects[f"users/{user_id}/a.bin"] = STORED
    request_id = uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ops.deletion_requests (id, subject_user_id, scope, storage_prefixes, "
            "requested_at, due_at) VALUES (%s, %s, 'account', ARRAY[%s], "
            "now() - interval '8 days', now() - interval '1 day')",
            [request_id, user_id, f"users/{user_id}/"],
        )

    assert run_job(migrated_url, identity_jobs.purge_account, request_id=str(request_id)) is None

    assert user_row(migrated_url, user_id) == ("active", None)
    assert f"users/{user_id}/a.bin" in storage.objects


def test_the_api_sees_only_its_own_deletion_requests(migrated_url: str, api_role_url: str) -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        for user in (mine, theirs):
            conn.execute(
                "INSERT INTO ops.deletion_requests (id, subject_user_id, scope) "
                "VALUES (%s, %s, 'account')",
                [uuid.uuid4(), user],
            )
    with psycopg.connect(api_role_url) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", [str(mine)])
        seen = conn.execute("SELECT subject_user_id FROM ops.deletion_requests").fetchall()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM ops.deletion_requests")
    assert seen == [(mine,)]
