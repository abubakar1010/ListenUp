"""Fixed-window rate limits backed by ops.rate_counters (Architecture 9.1).

Each hit is committed in its own short transaction, separate from the request's
transaction. Otherwise a refused sign-in, which rolls its request back, would also
roll back the count of failed attempts it was meant to record.
"""

import math
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.platform.database import Database
from listenup.platform.errors import ProblemError

_WINDOW_START = "date_bin(:window, now(), timestamptz '2000-01-01 00:00:00+00')"

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


# -- Counters of an amount, in the caller's transaction --------------------------------
# For limits on a quantity rather than on requests, such as seconds of new audio per
# learner per day (#41, Database Design 7: 'intake:user:<id>'). Unlike `hit`, they run
# in the caller's transaction, so the amount is counted only if its work commits.
# Windows start at fixed multiples of `window` from 2000-01-01 UTC: a one-day window
# runs from midnight to midnight UTC.

_ADD = text(f"""
INSERT INTO ops.rate_counters AS c (key, window_start, count)
VALUES (:key, {_WINDOW_START}, :amount)
ON CONFLICT (key, window_start) DO UPDATE SET count = c.count + :amount
""")

_COUNT = text(f"""
SELECT count FROM ops.rate_counters WHERE key = :key AND window_start = {_WINDOW_START}
""")


async def add_to_window(session: AsyncSession, key: str, window: timedelta, amount: int) -> None:
    """Add `amount` to the current window's count of `key`."""
    await session.execute(_ADD, {"key": key, "window": window, "amount": amount})


async def window_count(session: AsyncSession, key: str, window: timedelta) -> int:
    """The current window's count of `key`; 0 when nothing was counted."""
    count = await session.scalar(_COUNT, {"key": key, "window": window})
    return int(count or 0)
