"""Google OIDC: fixed provider endpoints; secrets never enter browser URLs or sessions."""

import json
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import Request
from sqlalchemy import text
from starlette.responses import RedirectResponse

from listenup.modules.identity.domain.tokens import new_token, token_hash
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
JWKS = "https://www.googleapis.com/oauth2/v3/certs"


def safe_next(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "/library"
    return (
        value
        if (
            value.startswith("/")
            and not value.startswith("//")
            and not parsed.netloc
            and not parsed.scheme
            and "\\" not in value
            and all(ord(c) >= 32 for c in value)
        )
        else "/library"
    )


class GoogleOIDC:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    def client(self) -> AsyncOAuth2Client:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise ProblemError(503, "google_unavailable", "Google sign-in is not configured.")
        return AsyncOAuth2Client(
            self.settings.google_client_id,
            self.settings.google_client_secret.get_secret_value(),
            redirect_uri=self.settings.google_redirect_uri,
            scope="openid email",
            code_challenge_method="S256",
            timeout=10,
        )

    def cookie_name(self, suffix: str = "") -> str:
        return ("__Host-" if self.settings.cookies_secure else "") + "listenup_oidc" + suffix

    def cookie(self, response: RedirectResponse, value: str, suffix: str = "") -> None:
        response.set_cookie(
            self.cookie_name(suffix),
            value,
            max_age=self.settings.oidc_lifetime_seconds,
            httponly=True,
            secure=self.settings.cookies_secure,
            samesite="lax",
            path="/",
        )

    async def put(
        self, browser: str, purpose: str, data: dict[str, Any], user_id: uuid.UUID | None = None
    ) -> str:
        token = new_token()
        async with self.database.transaction() as session:
            await session.execute(
                text("SELECT identity.put_oidc_flow(:t, :b, :u, :p, CAST(:d AS jsonb), :l)"),
                {
                    "t": token_hash(token),
                    "b": token_hash(browser),
                    "u": user_id,
                    "p": purpose,
                    "d": json.dumps(data),
                    "l": self.settings.oidc_lifetime_seconds,
                },
            )
        return token

    async def start(
        self, request: Request, next_path: str, user_id: uuid.UUID | None = None
    ) -> RedirectResponse:
        async with self.client() as client:
            browser, nonce, verifier = new_token(), new_token(), new_token()
            state = await self.put(
                browser,
                "login",
                {
                    "nonce": nonce,
                    "verifier": verifier,
                    "next": safe_next(next_path),
                    "user": str(user_id) if user_id else None,
                    "session": self.session_hash(request),
                    "started": int(time.time()),
                },
                user_id,
            )
            url, _ = client.create_authorization_url(
                AUTHORIZE,
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                **({"prompt": "login", "max_age": 0} if user_id else {}),
            )
        response = RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})
        self.cookie(response, browser)
        return response

    async def take(
        self, request: Request, token: str, purpose: str, *, consume: bool = True
    ) -> dict[str, Any]:
        browser = request.cookies.get(self.cookie_name(), "")
        # Consumption commits independently before exchanging a code or attempting a
        # transition. A failed token exchange must not make the callback reusable.
        async with self.database.transaction() as session:
            fn = "take_oidc_flow" if consume else "peek_oidc_flow"
            data = await session.scalar(
                text(f"SELECT identity.{fn}(:t, :b, :p)"),
                {"t": token_hash(token), "b": token_hash(browser), "p": purpose},
            )
        if not isinstance(data, dict):
            raise ProblemError(
                400, "google_auth_failed", "Google confirmation expired or is invalid. Try again."
            )
        return data

    async def claims(self, code: str, flow: dict[str, Any]) -> dict[str, Any]:
        from authlib.jose import JsonWebToken
        from authlib.oidc.core import CodeIDToken

        try:
            async with self.client() as client:
                tokens = await client.fetch_token(TOKEN, code=code, code_verifier=flow["verifier"])
                keys = await client.get(JWKS)
                keys.raise_for_status()
            claims = JsonWebToken(["RS256"]).decode(
                tokens["id_token"],
                keys.json(),
                claims_cls=CodeIDToken,
                claims_options={
                    "iss": {
                        "essential": True,
                        "values": ["https://accounts.google.com", "accounts.google.com"],
                    },
                    "aud": {"essential": True, "value": self.settings.google_client_id},
                    "exp": {"essential": True},
                    "iat": {"essential": True},
                },
                claims_params={
                    "nonce": flow["nonce"],
                    "client_id": self.settings.google_client_id,
                    "access_token": tokens.get("access_token"),
                },
            )
            claims.validate(leeway=0)
            from listenup.modules.identity.domain.credentials import email_problem

            if (
                claims.get("email_verified") is not True
                or not isinstance(claims.get("email"), str)
                or email_problem(claims["email"])
                or not isinstance(claims.get("sub"), str)
                or not 1 <= len(claims["sub"]) <= 255
            ):
                raise ValueError("invalid identity claims")
            if flow.get("user"):
                auth_time = claims.get("auth_time")
                if (
                    not isinstance(auth_time, int)
                    or auth_time < flow["started"] - 5
                    or auth_time > int(time.time()) + 5
                ):
                    raise ValueError("fresh authentication required")
            return dict(claims)
        except Exception:
            # Provider errors may contain codes or tokens; never expose their text.
            raise ProblemError(
                400, "google_auth_failed", "Google could not confirm your account. Try again."
            ) from None

    def session_hash(self, request: Request) -> str:
        from listenup.modules.identity.service import session_cookie_name

        return token_hash(
            request.cookies.get(session_cookie_name(self.settings.cookies_secure), "")
        ).hex()

    async def deletion_proof(self, request: Request, learner: uuid.UUID) -> bool:
        proof = request.cookies.get(self.cookie_name("_delete"))
        if not proof:
            return False
        data = await self.take(request, proof, "delete")
        if data["user"] != str(learner) or data["session"] != self.session_hash(request):
            raise ProblemError(
                403, "google_account_mismatch", "Confirm Google again for this account."
            )
        return True
