"""CSRF protection with a double-submit token (Architecture 9.1).

Every response to a browser without the token cookie sets one. The cookie is readable
by the web app, which sends its value back in the X-CSRF-Token header on every
POST, PUT, PATCH and DELETE. Another site can make the browser send the cookie but
cannot read it, so it cannot produce the header. The session cookie is also
SameSite=Lax, so this is a second, independent layer.
"""

import hmac
import secrets
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from listenup.platform.errors import problem_response

CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_cookie_name(secure: bool) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, set for
    # the whole site and not shared with subdomains.
    return "__Host-listenup_csrf" if secure else "listenup_csrf"


class CsrfMiddleware:
    def __init__(self, app: ASGIApp, *, secure: bool) -> None:
        self.app = app
        self.secure = secure
        self.cookie_name = csrf_cookie_name(secure)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
        token = cookie[self.cookie_name].value if self.cookie_name in cookie else None

        if scope["method"] not in SAFE_METHODS:
            sent = headers.get(CSRF_HEADER.encode(), b"").decode("latin-1")
            if not token or not hmac.compare_digest(sent, token):
                response = problem_response(
                    403,
                    "csrf_failed",
                    "This request is missing its security token. Reload the page and try again.",
                )
                await response(scope, receive, send)
                return

        if token:
            await self.app(scope, receive, send)
            return

        new_token = secrets.token_urlsafe(32)
        attributes = "Path=/; SameSite=Lax" + ("; Secure" if self.secure else "")
        set_cookie = f"{self.cookie_name}={new_token}; {attributes}".encode()

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"set-cookie", set_cookie)]
            await send(message)

        await self.app(scope, receive, send_with_cookie)
