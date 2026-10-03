"""RFC 9457 problem details with stable codes (Architecture 9.1).

Every error the API returns has the same shape:

    {"type": "/problems/step_locked", "title": "...", "status": 409,
     "detail": "...", "code": "step_locked", "request_id": "..."}

Clients branch on `code`, never on `title` or `detail`, which are for people.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from listenup.platform.log import current_request_id

PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger(__name__)

# Database triggers raise check_violation with one of these message prefixes
# (Database Design 8.2); each becomes a 409 with the same code.
DATABASE_RULE_CODES = {
    "step_locked": "This step is locked until the step before it is finished.",
    "entry_locked": "The entry choice cannot change once Transcript has started.",
    "segment_locked": "The Shadow segment cannot change once round 1 has started.",
    "segment_span": "A Shadow segment must be 60 to 90 seconds, or the whole short passage.",
}


class ProblemError(Exception):
    """Raise anywhere in request handling to return a problem-details response."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        title: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title or HTTPStatus(status).phrase
        self.headers = headers
        self.extensions = extensions


def problem_response(
    status: int,
    code: str,
    detail: str,
    *,
    title: str | None = None,
    headers: Mapping[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"/problems/{code}",
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
        **extensions,
    }
    request_id = current_request_id()
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


def _code_for_status(status: int) -> str:
    return HTTPStatus(status).phrase.lower().replace(" ", "_").replace("-", "_")


async def _problem(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(
        exc.status,
        exc.code,
        exc.detail,
        title=exc.title,
        headers=exc.headers,
        **exc.extensions,
    )


async def _http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return problem_response(
        exc.status_code, _code_for_status(exc.status_code), detail, headers=exc.headers
    )


async def _validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return problem_response(422, "validation_failed", "The request is not valid.", errors=errors)


def database_rule_code(exc: DBAPIError) -> str | None:
    """The stable code of a product rule the database refused, if this is one."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate != "23514":  # check_violation
        return None
    primary = getattr(getattr(exc.orig, "diag", None), "message_primary", None) or ""
    code = primary.split(":", 1)[0].strip()
    return code if code in DATABASE_RULE_CODES else None


async def _database(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    code = database_rule_code(exc)
    if code is not None:
        return problem_response(409, code, DATABASE_RULE_CODES[code])
    return await _unexpected(request, exc)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error", exc_info=exc)
    return _internal_error()


def _internal_error() -> JSONResponse:
    return problem_response(500, "internal_error", "Something went wrong on our side.")


class UnhandledErrorMiddleware:
    """Turns any other exception into a 500 problem, inside the request-id context.

    Starlette's own catch-all runs outside every middleware, where the request id is
    already gone, so the log line that matters most would lose it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            logger.error("unhandled error", exc_info=exc)
            if started:
                raise
            await _internal_error()(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers; call before adding RequestIdMiddleware, which must wrap
    UnhandledErrorMiddleware."""
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(DBAPIError, _database)
