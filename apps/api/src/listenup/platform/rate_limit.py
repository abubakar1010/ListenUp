"""Fixed-window rate limits backed by ops.rate_counters (Architecture 9.1).

Each hit is committed in its own short transaction, separate from the request's
transaction. Otherwise a refused sign-in, which rolls its request back, would also
roll back the count of failed attempts it was meant to record.
"""

import math
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text

from listenup.platform.database import Database
from listenup.platform.errors import ProblemError

_HIT = text("""
INSERT INTO ops.rate_counters AS c (key, window_start, count)
VALUES (:key, date_bin(:window, now(), timestamptz '2000-01-01 00:00:00+00'), 1)
ON CONFLICT (key, window_start) DO UPDATE SET count = c.count + 1
RETURNING c.count, extract(epoch FROM c.window_start + :window - now()) AS seconds_left
""")


@dataclass(frozen=True)
class Limit:
    name: str  # for example 'login', 'intake'
    max_hits: int
    window: timedelta


@dataclass(frozen=True)
class Hit:
    count: int
    allowed: bool
    retry_after: int  # whole seconds until the window resets


def ip_key(limit: Limit, ip: str) -> str:
    return f"{limit.name}:ip:{ip}"


def user_key(limit: Limit, user_id: object) -> str:
    return f"{limit.name}:user:{user_id}"


class RateLimiter:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def hit(self, limit: Limit, key: str) -> Hit:
        async with self.database.transaction() as session:
            count, seconds_left = (
                await session.execute(_HIT, {"key": key, "window": limit.window})
            ).one()
        return Hit(count, count <= limit.max_hits, max(1, math.ceil(float(seconds_left))))

    async def enforce(self, limit: Limit, key: str) -> Hit:
        """Count a hit and refuse the request with 429 once the limit is passed."""
        hit = await self.hit(limit, key)
        if not hit.allowed:
            raise ProblemError(
                429,
                "rate_limited",
                "Too many requests. Try again later.",
                headers={"Retry-After": str(hit.retry_after)},
                retry_after=hit.retry_after,
            )
        return hit
