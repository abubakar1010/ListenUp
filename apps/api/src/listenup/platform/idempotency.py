"""Idempotency-Key handling (Architecture 9.1; Database Design 7).

Submissions (gist, Dictation, round complete) accept an Idempotency-Key header, so a
retried request never creates a second attempt. The key is claimed in the same
transaction as the work:

- The first request inserts the key, does the work and stores the response; all of it
  commits together, or none of it does (a failed request leaves no key behind, so the
  retry runs again).
- A concurrent duplicate waits on the key's row lock until the first one commits, then
  replays its stored response.
- The same key with a different request is refused with `idempotency_key_reused`.
- Keys expire after 24 hours; an expired key is claimed again as new.
"""

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.platform.errors import ProblemError

REPLAYED_HEADER = "Idempotent-Replayed"
_VALID_KEY = re.compile(r"^[\x21-\x7e]{1,100}$")  # printable ASCII, no spaces

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key", description="Retry-safe key for this submission"),
]

Handler = Callable[[], Awaitable[tuple[int, Any]]]

_CLAIM = text("""
INSERT INTO ops.idempotency_keys (user_id, key, request_hash)
VALUES (:user_id, :key, :request_hash)
ON CONFLICT (user_id, key) DO UPDATE
   SET request_hash = EXCLUDED.request_hash, status_code = NULL, response = NULL,
       created_at = now()
 WHERE ops.idempotency_keys.created_at < now() - interval '24 hours'
RETURNING 1
""")

_LOOKUP = text("""
SELECT request_hash, status_code, response FROM ops.idempotency_keys
 WHERE user_id = :user_id AND key = :key
""")

_STORE = text("""
UPDATE ops.idempotency_keys SET status_code = :status_code, response = :response
 WHERE user_id = :user_id AND key = :key
""").bindparams(bindparam("response", type_=JSONB))


async def request_fingerprint(request: Request) -> bytes:
    """Method, path and body: the same key on another endpoint is a different request."""
    digest = hashlib.sha256()
    digest.update(request.method.encode())
    digest.update(b"\0")
    digest.update(request.url.path.encode())
    digest.update(b"\0")
    digest.update(await request.body())
    return digest.digest()


async def run_once(
    session: AsyncSession,
    learner: uuid.UUID,
    key: str | None,
    fingerprint: bytes,
    handler: Handler,
) -> JSONResponse:
    """Run `handler` at most once per (learner, key) and return its JSON response.

    `handler` returns (status code, JSON-serialisable body). Without a key the handler
    simply runs.
    """
    if key is None:
        status_code, body = await handler()
        return JSONResponse(body, status_code=status_code)
    if not _VALID_KEY.match(key):
        raise ProblemError(
            400, "invalid_idempotency_key", "Idempotency-Key must be 1 to 100 visible characters."
        )

    params = {"user_id": learner, "key": key}
    claimed = await session.execute(_CLAIM, {**params, "request_hash": fingerprint})
    if claimed.first() is None:
        return await _replay(session, params, fingerprint)

    status_code, body = await handler()
    await session.execute(_STORE, {**params, "status_code": status_code, "response": body})
    return JSONResponse(body, status_code=status_code)


async def _replay(
    session: AsyncSession, params: dict[str, Any], fingerprint: bytes
) -> JSONResponse:
    row = (await session.execute(_LOOKUP, params)).one()
    if bytes(row.request_hash) != fingerprint:
        raise ProblemError(
            422,
            "idempotency_key_reused",
            "This Idempotency-Key was already used for a different request.",
        )
    if row.status_code is None:
        raise ProblemError(
            409,
            "request_in_progress",
            "A request with this Idempotency-Key is still being processed.",
            headers={"Retry-After": "1"},
        )
    return JSONResponse(
        row.response, status_code=row.status_code, headers={REPLAYED_HEADER: "true"}
    )


def _references_resource(value: Any, resources: set[str]) -> bool:
    """Match structured resource references, never arbitrary learner text."""
    if isinstance(value, dict):
        reference_fields = {
            "id",
            "content_id",
            "session_id",
            "attempt_id",
            "card_id",
            "round_id",
            "mark_id",
            "media_object_id",
            "resource_id",
            "subject_id",
        }
        return any(
            (key in reference_fields and isinstance(child, str) and child in resources)
            or _references_resource(child, resources)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_references_resource(child, resources) for child in value)
    return False


async def forget_resource_responses(
    session: AsyncSession, learner: uuid.UUID, resources: set[str]
) -> int:
    """Remove cached learner text about deleted resources (DR-2).

    Call before acquiring deletion's parent locks, and again after its cascade in
    the same transaction. Lock existing keys first, in the same order as run_once:
    expired-key retries must never hold a key while deletion holds their session.
    The second pass catches new keys committed by requests the cascade waited for.
    Unrelated responses and every other learner's keys remain unchanged.
    """
    rows = (
        await session.execute(
            text(
                "SELECT key,response FROM ops.idempotency_keys WHERE user_id=:user "
                "ORDER BY key FOR UPDATE"
            ),
            {"user": learner},
        )
    ).all()
    removed = 0
    for key, response in rows:
        if _references_resource(response, resources):
            await session.execute(
                text("DELETE FROM ops.idempotency_keys WHERE user_id=:user AND key=:key"),
                {"user": learner, "key": key},
            )
            removed += 1
    return removed
