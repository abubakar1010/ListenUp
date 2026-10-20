"""Versioned consent to terms, privacy and voice recording (#104, FR-SH-17, NFR-SEC-4).

The app connects as a role with only the API's rights, so row-level security is in
force exactly as in production. Current versions come from the settings (ADR 0048).
"""

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.platform.config import Settings
from tests.integration.conftest import accepted_consents
from tests.integration.test_auth import PASSWORD, ClientFactory, login, unique_email
from tests.integration.test_auth import make_client as auth_client_factory

make_client = pytest.fixture(auth_client_factory.__wrapped__)

DEFAULT = Settings()


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def consent_rows(url: str, user_id: object) -> list[tuple[str, str, bool]]:
    """(kind, version, withdrawn) of every consent row of a learner, oldest first."""
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT kind, version, withdrawn_at IS NOT NULL FROM identity.consents "
            "WHERE user_id = %s ORDER BY granted_at, kind",
            [user_id],
        ).fetchall()
    return [(str(k), str(v), bool(w)) for k, v, w in rows]


def user_count(url: str, email: str) -> int:
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT count(*) FROM identity.users WHERE email = %s", [email]
        ).fetchone()
    assert row is not None
    return int(row[0])


def sign_up(client: TestClient, email: str, **consent: str | None) -> Any:
    body: dict[str, object] = {"email": email, "password": PASSWORD, **accepted_consents()}
    body.update(consent)
    return client.post(
        "/api/v1/auth/register", json={k: v for k, v in body.items() if v is not None}
    )


# -- AC1: a new account has terms and privacy rows with the current versions -----------


def test_signing_up_records_the_current_terms_and_privacy_versions(
    client: TestClient, migrated_url: str
) -> None:
    response = sign_up(client, unique_email())

    assert response.status_code == 201
    assert sorted(consent_rows(migrated_url, response.json()["id"])) == [
        ("privacy", DEFAULT.privacy_version, False),
        ("terms", DEFAULT.terms_version, False),
    ]
    assert response.json()["consents_required"] == []


@pytest.mark.parametrize("missing", ["terms_version", "privacy_version"])
def test_signing_up_without_accepting_is_refused_and_creates_no_account(
    client: TestClient, migrated_url: str, missing: str
) -> None:
    email = unique_email()

    response = sign_up(client, email, **{missing: None})

    assert response.status_code == 422
    assert response.json()["code"] == "consent_required"
    assert user_count(migrated_url, email) == 0
    assert client.get("/api/v1/me").status_code == 401


def test_signing_up_with_a_version_that_is_no_longer_current_is_refused(
    make_client: ClientFactory, migrated_url: str
) -> None:
    client = make_client(terms_version="terms-2")
    email = unique_email()

    response = sign_up(client, email, terms_version=DEFAULT.terms_version)

    assert response.status_code == 409
    problem = response.json()
    assert problem["code"] == "consent_version_changed"
    assert problem["current"]["terms"] == "terms-2"
    assert user_count(migrated_url, email) == 0


def test_the_current_versions_are_public_for_the_sign_up_form(client: TestClient) -> None:
    client.cookies.clear()

    response = client.get("/api/v1/auth/consent-versions")

    assert response.status_code == 200
    assert response.json() == {
        "terms": DEFAULT.terms_version,
        "privacy": DEFAULT.privacy_version,
        "voice_recording": DEFAULT.voice_consent_version,
    }


# -- AC2: a new version prompts existing learners once on next sign-in -----------------


def test_a_new_terms_version_prompts_once_on_the_next_sign_in(
    make_client: ClientFactory, migrated_url: str
) -> None:
    email = unique_email()
    user = sign_up(make_client(), email).json()["id"]

    # The new version is published: the app now runs with another terms label.
    later = make_client(terms_version="terms-2")
    signed_in = login(later, email)
    assert signed_in.status_code == 200  # type: ignore[attr-defined]
    assert signed_in.json()["consents_required"] == ["terms"]  # type: ignore[attr-defined]
    assert later.get("/api/v1/me").json()["consents_required"] == ["terms"]

    accepted = later.post("/api/v1/me/consents", json={"kind": "terms", "version": "terms-2"})
    assert accepted.status_code == 200
    assert later.get("/api/v1/me").json()["consents_required"] == []

    # Once: signing in again on another browser asks nothing.
    assert login(make_client(terms_version="terms-2"), email).json()["consents_required"] == []  # type: ignore[attr-defined]
    # The history keeps the version accepted at sign-up.
    assert sorted(consent_rows(migrated_url, user)) == [
        ("privacy", DEFAULT.privacy_version, False),
        ("terms", DEFAULT.terms_version, False),
        ("terms", "terms-2", False),
    ]


def test_a_new_privacy_version_prompts_for_privacy_only(make_client: ClientFactory) -> None:
    email = unique_email()
    sign_up(make_client(), email)

    later = make_client(privacy_version="privacy-2")

    assert login(later, email).json()["consents_required"] == ["privacy"]  # type: ignore[attr-defined]


def test_accepting_a_version_that_is_not_current_is_refused(
    make_client: ClientFactory, migrated_url: str
) -> None:
    email = unique_email()
    user = sign_up(make_client(), email).json()["id"]
    later = make_client(terms_version="terms-2")
    login(later, email)

    refused = later.post("/api/v1/me/consents", json={"kind": "terms", "version": "terms-3"})

    assert refused.status_code == 409
    assert refused.json()["code"] == "consent_version_changed"
    assert ("terms", "terms-3", False) not in consent_rows(migrated_url, user)
    assert later.get("/api/v1/me").json()["consents_required"] == ["terms"]


def test_granting_needs_the_csrf_header(client: TestClient, migrated_url: str) -> None:
    user = sign_up(client, unique_email()).json()["id"]
    del client.headers["X-CSRF-Token"]

    response = client.post(
        "/api/v1/me/consents",
        json={"kind": "voice_recording", "version": DEFAULT.voice_consent_version},
    )

    assert response.status_code == 403
    assert all(kind != "voice_recording" for kind, _, _ in consent_rows(migrated_url, user))


def test_the_settings_list_shows_every_accepted_version(make_client: ClientFactory) -> None:
    email = unique_email()
    sign_up(make_client(), email)
    later = make_client(terms_version="terms-2")
    login(later, email)
    later.post("/api/v1/me/consents", json={"kind": "terms", "version": "terms-2"})

    listed = later.get("/api/v1/me/consents").json()

    assert listed["current"]["terms"] == "terms-2"
    terms = [(c["version"], c["current"]) for c in listed["consents"] if c["kind"] == "terms"]
    assert sorted(terms) == sorted([("terms-2", True), (DEFAULT.terms_version, False)])
    assert all(c["withdrawn_at"] is None for c in listed["consents"])


# -- AC3: withdrawing voice consent sets withdrawn_at and blocks new rounds ------------


def voice_consent(api_role_url: str, user: str, settings: Settings = DEFAULT) -> bool:
    """What the Shadow module will ask before a round (#79), in the learner's RLS session."""
    from listenup.modules.identity.service import has_voice_consent
    from listenup.platform.database import Database, set_learner

    async def ask() -> bool:
        db = Database(api_role_url)
        try:
            async with db.transaction() as session:
                await set_learner(session, uuid.UUID(user))
                return await has_voice_consent(session, uuid.UUID(user), settings)
        finally:
            await db.dispose()

    return asyncio.run(ask())


def grant_voice(client: TestClient, version: str = DEFAULT.voice_consent_version) -> Any:
    return client.post("/api/v1/me/consents", json={"kind": "voice_recording", "version": version})


def withdraw(client: TestClient, kind: str) -> Any:
    return client.post("/api/v1/me/consents/withdraw", json={"kind": kind})


def test_withdrawing_voice_consent_sets_withdrawn_at_and_blocks_new_rounds(
    client: TestClient, migrated_url: str, api_role_url: str
) -> None:
    user = sign_up(client, unique_email()).json()["id"]
    assert voice_consent(api_role_url, user) is False
    assert grant_voice(client).status_code == 200
    assert voice_consent(api_role_url, user) is True

    response = withdraw(client, "voice_recording")

    assert response.status_code == 200
    voice = [c for c in response.json()["consents"] if c["kind"] == "voice_recording"]
    assert len(voice) == 1 and voice[0]["withdrawn_at"] is not None
    assert ("voice_recording", DEFAULT.voice_consent_version, True) in consent_rows(
        migrated_url, user
    )
    assert voice_consent(api_role_url, user) is False


def test_a_withdrawn_round_block_raises_voice_consent_required(
    client: TestClient, api_role_url: str
) -> None:
    from listenup.modules.identity.service import require_voice_consent
    from listenup.platform.database import Database, set_learner
    from listenup.platform.errors import ProblemError

    user = uuid.UUID(sign_up(client, unique_email()).json()["id"])
    grant_voice(client)
    withdraw(client, "voice_recording")

    async def ask() -> None:
        db = Database(api_role_url)
        try:
            async with db.transaction() as session:
                await set_learner(session, user)
                await require_voice_consent(session, user, DEFAULT)
        finally:
            await db.dispose()

    with pytest.raises(ProblemError) as refused:
        asyncio.run(ask())
    assert (refused.value.status, refused.value.code) == (403, "voice_consent_required")


def test_agreeing_again_after_withdrawing_allows_rounds_again(
    client: TestClient, api_role_url: str
) -> None:
    user = sign_up(client, unique_email()).json()["id"]
    grant_voice(client)
    withdraw(client, "voice_recording")

    assert grant_voice(client).status_code == 200

    assert voice_consent(api_role_url, user) is True


def test_voice_consent_to_an_older_version_does_not_allow_rounds(
    client: TestClient, api_role_url: str
) -> None:
    user = sign_up(client, unique_email()).json()["id"]
    grant_voice(client)

    newer = Settings(voice_consent_version="voice-2")

    assert voice_consent(api_role_url, user, newer) is False


@pytest.mark.parametrize("kind", ["terms", "privacy"])
def test_terms_and_privacy_cannot_be_withdrawn(
    client: TestClient, migrated_url: str, kind: str
) -> None:
    user = sign_up(client, unique_email()).json()["id"]

    refused = withdraw(client, kind)

    assert refused.status_code == 409
    assert refused.json()["code"] == "consent_not_withdrawable"
    assert all(not withdrawn for _, _, withdrawn in consent_rows(migrated_url, user))


def test_withdrawing_touches_only_the_callers_own_consent(
    make_client: ClientFactory, api_role_url: str
) -> None:
    a, b = make_client(), make_client()
    user_a = sign_up(a, unique_email()).json()["id"]
    sign_up(b, unique_email())
    grant_voice(a)
    grant_voice(b)

    withdraw(b, "voice_recording")

    assert voice_consent(api_role_url, user_a) is True
