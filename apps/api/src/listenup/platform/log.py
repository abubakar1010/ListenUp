"""Structured JSON logs with a request id (Architecture 12.3).

The request id comes from the X-Request-ID header or is generated, is returned in the
response, and is stored in a context variable so every log line written while
handling the request carries it. Code that enqueues a job passes
`current_request_id()` along, and the worker wraps the job in `request_id_bound(...)`,
so the id follows a request into the jobs it creates.

When tracing is on (ADR 0031), each line also carries the trace and span ids, so a
log line leads to its trace. Email addresses never reach the logs: the JSON formatter
replaces anything that looks like one, whatever logged it (Architecture 12.2).
"""

import json
import logging
import re
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
# Accept a caller's id only if it is short and plain, so it cannot inject into logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed with `extra=` and is logged.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "color_message"}


def current_request_id() -> str | None:
    return _request_id.get()


def _stamp_request_id(
    factory: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    def make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        span = trace.get_current_span().get_span_context()
        if span.is_valid and not hasattr(record, "trace_id"):
            record.trace_id = format(span.trace_id, "032x")
            record.span_id = format(span.span_id, "016x")
        return record

    return make_record


# Stamp the id when a line is logged, not when it is formatted: a handler may format
# it later, outside the request.
logging.setLogRecordFactory(_stamp_request_id(logging.getLogRecordFactory()))


@contextmanager
def request_id_bound(request_id: str | None) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


# The lookbehind makes a match start only where a run of address characters starts, so a
# long token with no "@" is scanned once, not once per character.
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
REDACTED_EMAIL = "[email]"


def redact(text: str) -> str:
    """Replace email addresses, so a log line never identifies a learner by address."""
    return _EMAIL.sub(REDACTED_EMAIL, text)


def _redact_value(value: Any) -> Any:
    """Redact every string inside a log value, before it is serialised.

    Redacting the serialised text instead would let an email that follows a JSON
    escape (`\\n`, `\\t`, `\\u00e9`) swallow the escape's letter and break the line.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {redact(str(key)): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_value(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact(str(value))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            entry["request_id"] = request_id
        for name, value in record.__dict__.items():
            if name not in _STANDARD_ATTRS and name != "request_id":
                entry[name] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(_redact_value(entry), default=str)


class RedactingFormatter(logging.Formatter):
    """Plain-text logs for an interactive terminal, with email addresses replaced."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn installs its own handlers; route its logs through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


class RequestIdMiddleware:
    """Pure ASGI middleware, so the context variable is visible to the route handler."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        with request_id_bound(request_id):
            await self.app(scope, receive, send_with_id)
