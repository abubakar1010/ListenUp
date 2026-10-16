"""Google OIDC boundary tests use deterministic provider responses, never live Google."""

import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import psycopg
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient

from tests.integration.test_auth import ClientFactory
from tests.integration.test_auth import make_client as auth_client_factory

make_client = pytest.fixture(auth_client_factory.__wrapped__)


def test_start_uses_configured_client_and_browser_bound_state(make_client: ClientFactory) -> None:
    client = make_client(
        google_client_id="google-client",
        google_client_secret="secret",
        google_redirect_uri="http://testserver/api/v1/auth/oidc/google/callback",
    )
    response = client.get("/api/v1/auth/oidc/google/start", follow_redirects=False)
    assert response.status_code == 303
    target = urlparse(response.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert query["client_id"] == ["google-client"]
    assert query["scope"] == ["openid email"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0] and query["nonce"][0]
    assert client.cookies.get("listenup_oidc")
    assert "no-store" in response.headers["cache-control"]


def test_missing_configuration_is_a_clear_refusal(make_client: ClientFactory) -> None:
    response = make_client().get("/api/v1/auth/oidc/google/start")
    assert response.status_code == 503
    assert response.json()["code"] == "google_unavailable"


@pytest.fixture
def google(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, dict[str, Any]]:
    client = make_client(
        google_client_id="google-client",
        google_client_secret="secret",
        google_redirect_uri="http://testserver/api/v1/auth/oidc/google/callback",
    )
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})
    options: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "email": f"{uuid.uuid4()}@example.com",
        "email_verified": True,
    }
    real_client = client.app.state.google.client

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("certs"):
            if options.get("provider_error") == "jwks":
                return httpx.Response(503)
            return httpx.Response(200, json={"keys": [key.as_dict(is_private=False)]})
        assert request.url.host == "oauth2.googleapis.com"
        if options.get("provider_error") == "token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        form = parse_qs(request.content.decode())
        assert form["code_verifier"][0]
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "google-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            **options,
        }
        token = jwt.encode({"alg": "RS256", "kid": "test"}, claims, key).decode()
        if options.get("tamper_signature"):
            parts = token.split(".")
            parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
            token = ".".join(parts)
        return httpx.Response(
            200,
            json={
                "access_token": "external-secret",
                "token_type": "Bearer",
                "id_token": options.get("raw_token", token),
            },
        )

    def mock_client() -> Any:
        adapter = real_client()
        adapter._transport = httpx.MockTransport(respond)
        # Proxy mounts otherwise bypass the test boundary.
        adapter._mounts = {}
        return adapter

    monkeypatch.setattr(client.app.state.google, "client", mock_client)
    return client, options


def begin(google: tuple[TestClient, dict[str, Any]], **params: str) -> str:
    client, options = google
    response = client.get("/api/v1/auth/oidc/google/start", params=params, follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    options["nonce"] = query["nonce"][0]
    return query["state"][0]


def callback(client: TestClient, state: str, **params: str) -> httpx.Response:
    return client.get(
        "/api/v1/auth/oidc/google/callback",
        params={"state": state, "code": "test-code", **params},
        follow_redirects=False,
    )


def test_google_creates_verified_passwordless_account_and_reuses_subject(
    google: Any, migrated_url: str
) -> None:
    client, claims = google
    response = callback(client, begin(google, next="/settings"))
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    me = client.get("/api/v1/me").json()
    assert me["email"] == claims["email"] and me["email_verified"] is True
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT password_hash FROM identity.users WHERE id = %s", [me["id"]]
        ).fetchone()
        assert row == (None,)
        assert conn.execute(
            "SELECT user_id FROM identity.oauth_accounts WHERE subject = %s", [claims["sub"]]
        ).fetchone() == (uuid.UUID(me["id"]),)
    client.post("/api/v1/auth/logout")
    claims["email"] = "changed@example.com"
    assert callback(client, begin(google)).status_code == 303
    assert client.get("/api/v1/me").json()["id"] == me["id"]


def test_verified_google_email_links_unverified_password_account_despite_password_lock(
    google: Any,
) -> None:
    from tests.integration.test_auth import PASSWORD

    client, claims = google
    registered = client.post(
        "/api/v1/auth/register", json={"email": claims["email"], "password": PASSWORD}
    ).json()
    client.post("/api/v1/auth/logout")
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": claims["email"], "password": "bad"})
    claims["email"] = claims["email"].upper()
    assert callback(client, begin(google)).status_code == 303
    assert client.get("/api/v1/me").json()["id"] == registered["id"]


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "wrong"},
        {"iss": "https://evil.example"},
        {"aud": "wrong"},
        {"exp": 1},
        {"email_verified": False},
        {"sub": ""},
        {"raw_token": "invalid"},
        {"tamper_signature": True},
        {"iat": int(time.time()) + 3600},
        {"azp": "another-client"},
        {"provider_error": "token"},
        {"provider_error": "jwks"},
    ],
)
def test_invalid_tokens_are_refused_without_creating_account(
    google: Any, migrated_url: str, change: dict[str, Any]
) -> None:
    client, claims = google
    state = begin(google)
    email = claims["email"]
    claims.update(change)
    response = callback(client, state)
    assert response.status_code == 400
    assert response.json()["code"] == "google_auth_failed"
    assert client.get("/api/v1/me").status_code == 401
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM identity.users WHERE email = %s", [email]
        ).fetchone() == (0,)
    assert callback(client, state).status_code == 400


def test_state_browser_binding_cancellation_and_replay(google: Any) -> None:
    client, _ = google
    state = begin(google)
    cookie = client.cookies.get("listenup_oidc")
    client.cookies.delete("listenup_oidc")
    assert callback(client, state).status_code == 400
    client.cookies.set("listenup_oidc", cookie, domain="testserver.local")
    assert callback(client, "tampered").status_code == 400
    cancelled = callback(client, state, error="access_denied")
    assert cancelled.status_code == 303
    assert cancelled.headers["location"] == "/sign-in?google=cancelled"
    assert callback(client, state).status_code == 400
    state = begin(google, next="https://evil.example")
    assert callback(client, state).headers["location"] == "/library"
    assert callback(client, state).status_code == 400


def test_google_restore_is_explicit_single_use_and_deadline_checked(
    google: Any, migrated_url: str
) -> None:
    client, _ = google
    assert callback(client, begin(google)).status_code == 303
    user = client.get("/api/v1/me").json()["id"]
    # Create a real deletion through the existing password route after setting a password.
    import asyncio

    from listenup.modules.identity.passwords import hash_password
    from tests.integration.test_auth import PASSWORD

    hashed = asyncio.run(hash_password(PASSWORD))
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE identity.users SET password_hash = %s WHERE id = %s", [hashed, user])
    assert (
        client.request(
            "DELETE", "/api/v1/me", json={"password": PASSWORD, "confirm": True}
        ).status_code
        == 202
    )
    response = callback(client, begin(google, next="/settings"))
    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in?google=restore"
    assert client.get("/api/v1/me").status_code == 401
    pending = client.get("/api/v1/auth/oidc/google/restore")
    assert pending.status_code == 200 and pending.json()["deletion_scheduled_at"]
    assert pending.json()["next_path"] == "/settings"
    assert (
        client.post("/api/v1/auth/oidc/google/restore", json={"restore": False}).status_code == 204
    )
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT status FROM identity.users WHERE id = %s", [user]
        ).fetchone() == ("pending_deletion",)
    assert (
        client.post("/api/v1/auth/oidc/google/restore", json={"restore": True}).status_code == 400
    )
    callback(client, begin(google))
    restored = client.post("/api/v1/auth/oidc/google/restore", json={"restore": True})
    assert restored.status_code == 200
    assert restored.json()["id"] == user
    assert client.get("/api/v1/me").status_code == 200
    assert (
        client.post("/api/v1/auth/oidc/google/restore", json={"restore": True}).status_code == 400
    )
    client.request("DELETE", "/api/v1/me", json={"password": PASSWORD, "confirm": True})
    callback(client, begin(google))
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET deletion_scheduled_at = now() WHERE id = %s", [user]
        )
    assert (
        client.post("/api/v1/auth/oidc/google/restore", json={"restore": True}).status_code == 401
    )
    assert callback(client, begin(google)).status_code == 401


def test_google_only_deletion_requires_fresh_matching_identity_and_explicit_confirmation(
    google: Any, migrated_url: str
) -> None:
    client, claims = google
    callback(client, begin(google))
    user = client.get("/api/v1/me").json()["id"]
    assert client.request("DELETE", "/api/v1/me", json={"confirm": True}).status_code == 403
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time())
    subject = claims["sub"]
    claims["sub"] = "someone-else"
    assert callback(client, state).status_code == 403
    claims["sub"] = subject
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time()) - 3600
    assert callback(client, state).status_code == 400
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time())
    response = callback(client, state)
    assert response.status_code == 303
    assert response.headers["location"] == "/settings/delete-account?google=confirmed"
    # Returning from Google alone does not delete anything.
    assert client.get("/api/v1/me").status_code == 200
    assert client.request("DELETE", "/api/v1/me", json={"confirm": False}).status_code == 422
    deleted = client.request("DELETE", "/api/v1/me", json={"confirm": True})
    assert deleted.status_code == 202
    assert client.get("/api/v1/me").status_code == 401
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT status FROM identity.users WHERE id = %s", [user]
        ).fetchone() == ("pending_deletion",)


def test_expired_state_and_reauth_proof_are_refused(google: Any, migrated_url: str) -> None:
    client, claims = google
    state = begin(google)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE identity.oidc_flows SET expires_at = now()")
    assert callback(client, state).status_code == 400
    callback(client, begin(google))
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time())
    assert callback(client, state).status_code == 303
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE identity.oidc_flows SET expires_at = now()")
    assert client.request("DELETE", "/api/v1/me", json={"confirm": True}).status_code == 400
    assert client.get("/api/v1/me").status_code == 200


def test_google_start_has_ip_rate_limit(make_client: ClientFactory) -> None:
    client = make_client(
        google_client_id="google-client", google_client_secret="secret", login_ip_limit=2
    )
    for _ in range(2):
        assert (
            client.get("/api/v1/auth/oidc/google/start", follow_redirects=False).status_code == 303
        )
    limited = client.get("/api/v1/auth/oidc/google/start", follow_redirects=False)
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"


def test_google_reauth_is_bound_to_the_original_login_session(
    google: Any, migrated_url: str
) -> None:
    import asyncio

    from listenup.modules.identity.passwords import hash_password
    from tests.integration.test_auth import PASSWORD

    client, claims = google
    callback(client, begin(google))
    user = client.get("/api/v1/me").json()["id"]
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET password_hash = %s WHERE id = %s",
            [asyncio.run(hash_password(PASSWORD)), user],
        )
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time())
    client.post("/api/v1/auth/login", json={"email": claims["email"], "password": PASSWORD})
    assert callback(client, state).status_code == 403
    state = begin(google, purpose="reauth")
    claims["auth_time"] = int(time.time())
    assert callback(client, state).status_code == 303
    client.post("/api/v1/auth/login", json={"email": claims["email"], "password": PASSWORD})
    assert client.request("DELETE", "/api/v1/me", json={"confirm": True}).status_code == 403
    assert client.get("/api/v1/me").status_code == 200

    assert (
        client.request(
            "DELETE", "/api/v1/me", json={"password": PASSWORD, "confirm": True}
        ).status_code
        == 202
    )


def test_unlinked_subject_can_create_new_account_with_released_email(
    google: Any, migrated_url: str
) -> None:
    client, claims = google
    callback(client, begin(google))
    old = client.get("/api/v1/me").json()["id"]
    client.post("/api/v1/auth/logout")
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() WHERE id = %s",
            [old],
        )
    assert callback(client, begin(google)).status_code == 401
    claims["sub"] = str(uuid.uuid4())
    assert callback(client, begin(google)).status_code == 303
    assert client.get("/api/v1/me").json()["id"] != old


def test_reauth_requires_a_signed_in_learner(google: Any) -> None:
    client, _ = google
    assert client.get("/api/v1/auth/oidc/google/start?purpose=reauth").status_code == 401


def test_concurrent_callbacks_create_one_identity(api_role_url: str) -> None:
    import asyncio

    from listenup.modules.identity.repository import google_account
    from listenup.platform.database import Database

    subject, email = str(uuid.uuid4()), f"{uuid.uuid4()}@example.com"

    async def race() -> list[uuid.UUID]:
        db = Database(api_role_url)

        async def resolve() -> uuid.UUID:
            async with db.transaction() as session:
                return (await google_account(session, subject, email)).id

        try:
            return await asyncio.gather(resolve(), resolve())
        finally:
            await db.dispose()

    ids = asyncio.run(race())
    assert ids[0] == ids[1]


def test_keep_deleted_also_signs_out_a_session_created_in_another_tab(
    google: Any, migrated_url: str
) -> None:
    client, _ = google
    callback(client, begin(google))
    user = client.get("/api/v1/me").json()["id"]
    client.post("/api/v1/auth/logout")
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE identity.users SET status = 'pending_deletion', "
            "deletion_scheduled_at = now() + interval '7 days' WHERE id = %s",
            [user],
        )
    assert callback(client, begin(google)).status_code == 303
    client.post(
        "/api/v1/auth/register",
        json={"email": f"{uuid.uuid4()}@example.com", "password": "a valid new password"},
    )
    assert client.get("/api/v1/me").status_code == 200
    assert (
        client.post("/api/v1/auth/oidc/google/restore", json={"restore": False}).status_code == 204
    )
    assert client.get("/api/v1/me").status_code == 401
