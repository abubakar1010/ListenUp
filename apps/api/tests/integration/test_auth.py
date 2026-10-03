"""Register, sign in and sign out (#29: FR-ACC-1, FR-ACC-2, NFR-SEC-1, NFR-USE-3, D17).

The app connects as a role with only the API's rights, so row-level security is in
force exactly as in production.
"""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.platform.config import Settings
from tests.integration.conftest import with_csrf

PASSWORD = "correct horse battery"

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(api_role_url: str) -> Iterator[ClientFactory]:
    opened: list[TestClient] = []

    def make(**settings: object) -> TestClient:
        app = create_app(Settings(database_url=api_role_url, log_json=False, **settings))  # type: ignore[arg-type]
        client = TestClient(app, raise_server_exceptions=False, client=("203.0.113.7", 50000))
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
    return f"learner-{datetime.now(UTC).timestamp()}-{id(object())}@example.com"


def register(client: TestClient, email: str, password: str = PASSWORD) -> object:
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str, password: str = PASSWORD) -> object:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def session_cookie(client: TestClient) -> str:
    return next(v for k, v in client.cookies.items() if k.endswith("listenup_session"))


def test_registering_signs_the_learner_in(client: TestClient) -> None:
    email = unique_email()

    response = register(client, email)

    assert response.status_code == 201  # type: ignore[attr-defined]
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_only_hashes_are_stored(client: TestClient, migrated_url: str) -> None:
    email = unique_email()
    register(client, email)
    token = session_cookie(client)

    with psycopg.connect(migrated_url) as conn:
        password_hash, token_hash = conn.execute(
            "SELECT u.password_hash, s.token_hash FROM identity.users u "
            "JOIN identity.auth_sessions s ON s.user_id = u.id WHERE u.email = %s",
            [email],
        ).fetchone()
    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash
    assert bytes(token_hash) == hashlib.sha256(token.encode()).digest()


def test_a_state_changing_request_without_the_csrf_header_is_refused(
    client: TestClient,
) -> None:
    del client.headers["X-CSRF-Token"]

    response = register(client, unique_email())

    assert response.status_code == 403  # type: ignore[attr-defined]
    assert response.json()["code"] == "csrf_failed"  # type: ignore[attr-defined]


def test_the_same_email_cannot_register_twice(client: TestClient) -> None:
    email = unique_email()
    register(client, email)

    response = register(client, email.upper())

    assert response.status_code == 409  # type: ignore[attr-defined]
    assert response.json()["code"] == "email_taken"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [("not-an-email", PASSWORD, "invalid_email"), ("ok@example.com", "short", "weak_password")],
)
def test_bad_registrations_say_what_to_fix(
    client: TestClient, email: str, password: str, code: str
) -> None:
    response = register(client, email, password)

    assert response.status_code == 422  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["code"] == code
    assert body["detail"]


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(client: TestClient) -> None:
    email = unique_email()
    register(client, email)

    wrong = login(client, email, "wrong password!")
    unknown = login(client, unique_email())

    assert wrong.status_code == unknown.status_code == 401  # type: ignore[attr-defined]
    assert wrong.json()["detail"] == unknown.json()["detail"]  # type: ignore[attr-defined]


def test_signing_out_ends_the_session(client: TestClient, migrated_url: str) -> None:
    email = unique_email()
    register(client, email)
    token = session_cookie(client)

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").json()["code"] == "not_signed_in"
    with psycopg.connect(migrated_url) as conn:
        left = conn.execute(
            "SELECT count(*) FROM identity.auth_sessions WHERE token_hash = %s",
            [hashlib.sha256(token.encode()).digest()],
        ).fetchone()
    assert left == (0,)


def test_a_second_browser_shows_the_same_account(make_client: ClientFactory) -> None:
    email = unique_email()
    first, second = make_client(), make_client()
    register(first, email)

    login(second, email)

    assert first.get("/api/v1/me").json() == second.get("/api/v1/me").json()


def test_signing_in_replaces_the_previous_session(client: TestClient) -> None:
    email = unique_email()
    register(client, email)
    before = session_cookie(client)

    login(client, email)

    after = session_cookie(client)
    assert after != before
    client.cookies.set("listenup_session", before)
    assert client.get("/api/v1/me").json()["code"] == "not_signed_in"


def test_five_failures_lock_the_account_even_for_the_right_password(
    client: TestClient,
) -> None:
    email = unique_email()
    register(client, email)
    client.post("/api/v1/auth/logout")

    codes = [login(client, email, "wrong password!").json()["code"] for _ in range(5)]  # type: ignore[attr-defined]
    locked = login(client, email)

    assert codes == ["invalid_credentials"] * 4 + ["account_locked"]
    assert locked.status_code == 429  # type: ignore[attr-defined]
    body = locked.json()  # type: ignore[attr-defined]
    assert body["code"] == "account_locked"
    until = datetime.fromisoformat(body["locked_until"])
    assert timedelta(minutes=14) < until - datetime.now(UTC) <= timedelta(minutes=15)
    assert 0 < int(locked.headers["Retry-After"]) <= 15 * 60  # type: ignore[attr-defined]


def test_after_the_lock_ends_the_right_password_works_and_failures_reset(
    client: TestClient, migrated_url: str
) -> None:
    email = unique_email()
    register(client, email)
    client.post("/api/v1/auth/logout")
    for _ in range(5):
        login(client, email, "wrong password!")
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.rate_counters SET window_start = window_start - interval '16 minutes' "
            "WHERE key LIKE 'login_lock:%%'"
        )

    assert login(client, email).status_code == 200  # type: ignore[attr-defined]

    with psycopg.connect(migrated_url) as conn:
        left = conn.execute(
            "SELECT count(*) FROM ops.rate_counters WHERE key LIKE 'login\\_%%:user:%%'"
        ).fetchone()
    assert left == (0,)
    # A fresh failure does not re-lock: the count started again from zero.
    assert login(client, email, "wrong password!").json()["code"] == "invalid_credentials"  # type: ignore[attr-defined]


def test_the_lock_threshold_and_duration_come_from_configuration(
    make_client: ClientFactory,
) -> None:
    client = make_client(login_lock_threshold=2, login_lock_minutes=3)
    email = unique_email()
    register(client, email)
    client.post("/api/v1/auth/logout")

    login(client, email, "wrong password!")
    locked = login(client, email, "wrong password!").json()  # type: ignore[attr-defined]

    assert locked["code"] == "account_locked"
    until = datetime.fromisoformat(locked["locked_until"])
    assert timedelta(minutes=2) < until - datetime.now(UTC) <= timedelta(minutes=3)


def test_one_ip_is_limited_across_accounts(make_client: ClientFactory) -> None:
    client = make_client(login_ip_limit=3)

    codes = [login(client, unique_email()).json()["code"] for _ in range(4)]  # type: ignore[attr-defined]
    limited = login(client, unique_email())

    assert codes == ["invalid_credentials"] * 3 + ["rate_limited"]
    assert limited.status_code == 429  # type: ignore[attr-defined]
    assert "Try again later" in limited.json()["detail"]  # type: ignore[attr-defined]


def test_signing_in_restores_an_account_waiting_for_deletion(
    client: TestClient, migrated_url: str
) -> None:
    email = unique_email()
    register(client, email)
    client.post("/api/v1/auth/logout")
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() + interval '7 days' WHERE email = %s",
            [email],
        )

    assert login(client, email).status_code == 200  # type: ignore[attr-defined]

    with psycopg.connect(migrated_url) as conn:
        status = conn.execute(
            "SELECT status FROM identity.users WHERE email = %s", [email]
        ).fetchone()
    assert status == ("active",)


def test_me_needs_a_signed_in_learner(client: TestClient) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_signed_in"
