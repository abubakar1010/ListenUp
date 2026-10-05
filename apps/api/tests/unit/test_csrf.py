"""Double-submit CSRF protection (Architecture 9.1; acceptance criteria of #29)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from listenup.platform.csrf import CsrfMiddleware


def make_client(secure: bool = False) -> TestClient:
    app = FastAPI()
    app.add_middleware(CsrfMiddleware, secure=secure)

    @app.get("/read")
    def read() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/write")
    def write() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_a_read_sets_a_readable_token_cookie() -> None:
    response = make_client().get("/read")

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("listenup_csrf=")
    assert "SameSite=Lax" in cookie
    assert "HttpOnly" not in cookie  # the web app must be able to read it


def test_a_write_without_the_header_is_refused() -> None:
    client = make_client()
    client.get("/read")

    response = client.post("/write")

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_a_write_with_a_wrong_header_is_refused() -> None:
    client = make_client()
    client.get("/read")

    assert client.post("/write", headers={"X-CSRF-Token": "guess"}).status_code == 403


def test_a_write_with_the_matching_header_passes() -> None:
    client = make_client()
    client.get("/read")
    token = client.cookies["listenup_csrf"]

    assert client.post("/write", headers={"X-CSRF-Token": token}).json() == {"ok": True}


def test_secure_deployments_use_a_host_only_secure_cookie() -> None:
    cookie = make_client(secure=True).get("/read").headers["set-cookie"]
    assert cookie.startswith("__Host-listenup_csrf=")
    assert "Secure" in cookie
