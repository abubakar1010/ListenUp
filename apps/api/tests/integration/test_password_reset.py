"""Reset a forgotten password by email (#31: FR-ACC-3, NFR-SEC-1, NFR-USE-3).

The app connects as a role with only the API's rights, so row-level security is in
force exactly as in production. Emails go to an in-memory outbox instead of SMTP, and
queued jobs run in a real Procrastinate worker that stops once the queue is empty.
"""

import asyncio
import hashlib
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import procrastinate
import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from listenup.main import create_app
from listenup.modules.identity import jobs as identity_jobs
from listenup.modules.notifications import service as notifications
from listenup.modules.notifications.service import EmailContent
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import Lane, app, configure_runtime
from tests.integration.conftest import conninfo_to_url, with_csrf

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"
TOKEN_IN_LINK = re.compile(r"/reset-password#token=([A-Za-z0-9_-]+)")

ClientFactory = Callable[..., TestClient]


class Outbox:
    def __init__(self) -> None:
        self.sent: list[EmailContent] = []

    async def send(self, content: EmailContent) -> None:
        self.sent.append(content)

    def tokens(self) -> list[str]:
        return [
            match.group(1)
            for mail in self.sent
            for match in [TOKEN_IN_LINK.search(mail.text)]
            if match
        ]


@pytest.fixture
def outbox(migrated_url: str) -> Iterator[Outbox]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    box = Outbox()
    notifications.use_transport(box)
    yield box
    notifications.use_transport(None)


@pytest.fixture
def make_client(api_role_url: str, outbox: Outbox) -> Iterator[ClientFactory]:
    opened: list[TestClient] = []

    def make(**settings: object) -> TestClient:
        app_ = create_app(Settings(database_url=api_role_url, log_json=False, **settings))  # type: ignore[arg-type]
        client = TestClient(app_, raise_server_exceptions=False, client=("203.0.113.9", 50000))
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
    return f"reset-{datetime.now(UTC).timestamp()}-{id(object())}@example.com"


def register(client: TestClient, email: str, password: str = PASSWORD) -> Response:
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str, password: str = PASSWORD) -> Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def request_reset(client: TestClient, email: str) -> Response:
    return client.post("/api/v1/auth/password-reset", json={"email": email})


def confirm(client: TestClient, token: str, password: str = NEW_PASSWORD) -> Response:
    return client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": password}
    )


def deliver(migrated_url: str) -> None:
    """Run every queued background job, then stop."""

    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=2)
        configure_runtime(database)
        try:
            with app.replace_connector(procrastinate.PsycopgConnector(conninfo=migrated_url)):
                async with app.open_async():
                    await app.run_worker_async(
                        queues=[Lane.BACKGROUND.value], wait=False, install_signal_handlers=False
                    )
        finally:
            await database.dispose()

    asyncio.run(run())


def reset_jobs(migrated_url: str) -> list[dict[str, Any]]:
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT status::text, args FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = %s ORDER BY id",
            [identity_jobs.SEND_PASSWORD_RESET],
        ).fetchall()
    return [{"status": status, "args": args} for status, args in rows]


def signed_up(client: TestClient) -> str:
    """A registered learner, signed out again."""
    email = unique_email()
    register(client, email)
    client.post("/api/v1/auth/logout")
    return email


def emailed_token(client: TestClient, migrated_url: str, outbox: Outbox, email: str) -> str:
    assert request_reset(client, email).status_code == 202
    deliver(migrated_url)
    return outbox.tokens()[-1]


def test_unknown_and_registered_emails_get_the_same_answer(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)

    known = request_reset(client, email)
    unknown = request_reset(client, unique_email())

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "If an account uses this email" in known.json()["detail"]
    deliver(migrated_url)
    assert [mail.to for mail in outbox.sent] == [email]


def test_the_email_job_is_queued_without_the_token(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)

    request_reset(client, email)

    [queued] = reset_jobs(migrated_url)
    assert queued["status"] == "todo"
    assert set(queued["args"]) <= {"user_id", "requested_at", "_request_id"}
    assert outbox.sent == []  # nothing is sent while handling the request


def test_the_email_job_is_queued_in_the_request_transaction(
    client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = signed_up(client)
    real_enqueue = identity_jobs.enqueue

    async def enqueue_then_fail(*args: Any, **kwargs: Any) -> int | None:
        await real_enqueue(*args, **kwargs)
        raise RuntimeError("the request fails after queueing")

    monkeypatch.setattr(identity_jobs, "enqueue", enqueue_then_fail)

    assert request_reset(client, email).status_code == 500
    assert reset_jobs(migrated_url) == []


def test_the_job_emails_a_link_whose_token_is_stored_only_as_a_hash(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)

    token = emailed_token(client, migrated_url, outbox, email)

    [mail] = outbox.sent
    assert mail.subject == "Reset your ListenUp password"
    assert f"/reset-password#token={token}" in mail.html
    assert "1 hour" in mail.text
    assert [job["status"] for job in reset_jobs(migrated_url)] == ["succeeded"]
    with psycopg.connect(migrated_url) as conn:
        stored, purpose, lifetime = conn.execute(
            "SELECT t.token_hash, t.purpose, t.expires_at - t.created_at "
            "FROM identity.one_time_tokens t JOIN identity.users u ON u.id = t.user_id "
            "WHERE u.email = %s",
            [email],
        ).fetchone()
        queued_args = conn.execute(
            "SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE args::text LIKE %s",
            [f"%{token}%"],
        ).fetchone()
    assert bytes(stored) == hashlib.sha256(token.encode()).digest()
    assert purpose == "reset_password"
    assert timedelta(minutes=59) < lifetime <= timedelta(hours=1)
    assert queued_args == (0,)


def test_a_link_works_once(client: TestClient, migrated_url: str, outbox: Outbox) -> None:
    email = signed_up(client)
    token = emailed_token(client, migrated_url, outbox, email)

    first = confirm(client, token)
    again = confirm(client, token, "yet another passphrase")

    assert first.status_code == 204
    assert again.status_code == 400
    body = again.json()
    assert body["code"] == "invalid_reset_link"
    assert "expired or was already used" in body["detail"]
    assert login(client, email, NEW_PASSWORD).status_code == 200


def test_an_expired_link_is_refused(client: TestClient, migrated_url: str, outbox: Outbox) -> None:
    email = signed_up(client)
    token = emailed_token(client, migrated_url, outbox, email)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.one_time_tokens SET expires_at = now() - interval '1 second' "
            "WHERE token_hash = %s",
            [hashlib.sha256(token.encode()).digest()],
        )

    response = confirm(client, token)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_reset_link"
    assert login(client, email).status_code == 200  # the old password still works


def test_an_unknown_token_is_refused(client: TestClient) -> None:
    response = confirm(client, "not-a-real-token")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_reset_link"


def test_a_new_request_retires_the_older_link(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)
    older = emailed_token(client, migrated_url, outbox, email)
    newer = emailed_token(client, migrated_url, outbox, email)

    assert older != newer
    assert confirm(client, older).json()["code"] == "invalid_reset_link"
    assert confirm(client, newer).status_code == 204


def test_the_new_password_works_and_the_old_one_does_not(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)
    token = emailed_token(client, migrated_url, outbox, email)

    assert confirm(client, token).status_code == 204

    assert login(client, email, PASSWORD).json()["code"] == "invalid_credentials"
    assert login(client, email, NEW_PASSWORD).status_code == 200
    with psycopg.connect(migrated_url) as conn:
        [password_hash] = conn.execute(
            "SELECT password_hash FROM identity.users WHERE email = %s", [email]
        ).fetchone()
    assert password_hash.startswith("$argon2id$")


def test_a_reset_signs_out_every_session(
    make_client: ClientFactory, migrated_url: str, outbox: Outbox
) -> None:
    laptop, phone, anonymous = make_client(), make_client(), make_client()
    email = unique_email()
    register(laptop, email)
    login(phone, email)
    token = emailed_token(anonymous, migrated_url, outbox, email)

    assert confirm(anonymous, token).status_code == 204

    assert laptop.get("/api/v1/me").json()["code"] == "not_signed_in"
    assert phone.get("/api/v1/me").json()["code"] == "not_signed_in"
    with psycopg.connect(migrated_url) as conn:
        left = conn.execute(
            "SELECT count(*) FROM identity.auth_sessions s JOIN identity.users u "
            "ON u.id = s.user_id WHERE u.email = %s",
            [email],
        ).fetchone()
    assert left == (0,)


def test_a_reset_lifts_the_sign_in_lockout(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)
    for _ in range(5):
        login(client, email, "wrong password!")
    assert login(client, email).json()["code"] == "account_locked"
    token = emailed_token(client, migrated_url, outbox, email)

    assert confirm(client, token).status_code == 204

    assert login(client, email, NEW_PASSWORD).status_code == 200


def test_a_weak_new_password_keeps_the_link_usable(
    client: TestClient, migrated_url: str, outbox: Outbox
) -> None:
    email = signed_up(client)
    token = emailed_token(client, migrated_url, outbox, email)

    weak = confirm(client, token, "short")

    assert weak.status_code == 422
    assert weak.json()["code"] == "weak_password"
    assert confirm(client, token).status_code == 204


def test_an_address_gets_few_emails_but_the_same_answer(
    make_client: ClientFactory, migrated_url: str, outbox: Outbox
) -> None:
    client = make_client(password_reset_email_limit=1)
    email = signed_up(client)

    first = request_reset(client, email)
    deliver(migrated_url)
    second = request_reset(client, email.upper())
    deliver(migrated_url)

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(outbox.sent) == 1


def test_one_ip_is_limited(make_client: ClientFactory) -> None:
    client = make_client(password_reset_ip_limit=2)

    codes = [request_reset(client, unique_email()).status_code for _ in range(3)]

    assert codes == [202, 202, 429]
    limited = request_reset(client, unique_email())
    assert limited.json()["code"] == "rate_limited"


def test_an_invalid_email_is_explained(client: TestClient) -> None:
    response = request_reset(client, "not-an-email")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_email"


def test_the_api_role_sees_no_tokens_without_a_learner(
    client: TestClient, migrated_url: str, api_role_url: str, outbox: Outbox
) -> None:
    emailed_token(client, migrated_url, outbox, signed_up(client))

    with psycopg.connect(api_role_url) as conn:
        visible = conn.execute("SELECT count(*) FROM identity.one_time_tokens").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO identity.one_time_tokens (token_hash, user_id, purpose, expires_at) "
                "SELECT 'x'::bytea, id, 'reset_password', now() + interval '1 hour' "
                "FROM identity.users LIMIT 1"
            )
    assert visible == (0,)
