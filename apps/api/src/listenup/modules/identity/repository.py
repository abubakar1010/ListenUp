"""SQL for the identity module."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    email: str
    password_hash: str | None
    status: str


async def insert_user(
    session: AsyncSession, user_id: uuid.UUID, email: str, password_hash: str
) -> bool:
    """False when the email is already registered (compared without case)."""
    result = await session.execute(
        text("""
        INSERT INTO identity.users (id, email, password_hash) VALUES (:id, :email, :hash)
        ON CONFLICT (email) DO NOTHING RETURNING id
        """),
        {"id": user_id, "email": email, "hash": password_hash},
    )
    return result.first() is not None


async def find_account(session: AsyncSession, email: str) -> Account | None:
    row = (
        await session.execute(
            text(
                "SELECT id, email::text, password_hash, status FROM identity.users "
                "WHERE email = :email"
            ),
            {"email": email},
        )
    ).first()
    return Account(*row) if row else None


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, email::text AS email, display_name, "
                    "email_verified_at IS NOT NULL AS email_verified "
                    "FROM identity.users WHERE id = :id"
                ),
                {"id": user_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def update_password_hash(session: AsyncSession, user_id: uuid.UUID, new_hash: str) -> None:
    await session.execute(
        text("UPDATE identity.users SET password_hash = :hash WHERE id = :id"),
        {"hash": new_hash, "id": user_id},
    )


async def restore_account(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Signing in during the 7-day grace period cancels the deletion (D9)."""
    await session.execute(
        text("""
        UPDATE identity.users SET status = 'active', deletion_scheduled_at = NULL
         WHERE id = :id AND status = 'pending_deletion'
        """),
        {"id": user_id},
    )


async def create_auth_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    token_hash: bytes,
    lifetime: timedelta,
    user_agent: str | None,
    ip: str | None,
) -> None:
    await session.execute(
        text("""
        INSERT INTO identity.auth_sessions (id, user_id, token_hash, expires_at, user_agent, ip)
        VALUES (:id, :user_id, :token_hash, now() + :lifetime, :user_agent, CAST(:ip AS inet))
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "token_hash": token_hash,
            "lifetime": lifetime,
            "user_agent": (user_agent or "")[:400] or None,
            "ip": ip,
        },
    )


async def resolve_auth_session(session: AsyncSession, token_hash: bytes) -> uuid.UUID | None:
    user_id = await session.scalar(
        text("SELECT identity.resolve_auth_session(:token_hash)"), {"token_hash": token_hash}
    )
    return uuid.UUID(str(user_id)) if user_id else None


async def delete_auth_session(session: AsyncSession, token_hash: bytes) -> None:
    await session.execute(
        text("DELETE FROM identity.auth_sessions WHERE token_hash = :token_hash"),
        {"token_hash": token_hash},
    )


# Sign-in lockout (D17), kept in ops.rate_counters as the Database Design describes:
# failures are counted in one-minute buckets under 'login_fail:user:<id>', so summing
# the buckets of the last N minutes gives a sliding window; reaching the threshold
# writes 'login_lock:user:<id>' with window_start = the moment of the lock.


def _fail_key(user_id: uuid.UUID) -> str:
    return f"login_fail:user:{user_id}"


def _lock_key(user_id: uuid.UUID) -> str:
    return f"login_lock:user:{user_id}"


async def locked_until(
    session: AsyncSession, user_id: uuid.UUID, lock: timedelta
) -> datetime | None:
    result: datetime | None = await session.scalar(
        text("""
        SELECT max(window_start) + :lock FROM ops.rate_counters
         WHERE key = :key AND window_start > now() - :lock
        """),
        {"key": _lock_key(user_id), "lock": lock},
    )
    return result


async def record_failure(
    session: AsyncSession, user_id: uuid.UUID, window: timedelta, threshold: int
) -> datetime | None:
    """Count one failed sign-in; returns when the lock ends if this one locked it."""
    await session.execute(
        text("""
        INSERT INTO ops.rate_counters AS c (key, window_start, count)
        VALUES (:key, date_trunc('minute', now()), 1)
        ON CONFLICT (key, window_start) DO UPDATE SET count = c.count + 1
        """),
        {"key": _fail_key(user_id)},
    )
    failures = await session.scalar(
        text("""
        SELECT coalesce(sum(count), 0) FROM ops.rate_counters
         WHERE key = :key AND window_start > now() - :window
        """),
        {"key": _fail_key(user_id), "window": window},
    )
    if int(failures or 0) < threshold:
        return None
    await session.execute(
        text("""
        INSERT INTO ops.rate_counters (key, window_start, count) VALUES (:key, now(), 1)
        ON CONFLICT DO NOTHING
        """),
        {"key": _lock_key(user_id)},
    )
    # The failures that caused this lock must not lock the account again once it ends.
    await session.execute(
        text("DELETE FROM ops.rate_counters WHERE key = :key"), {"key": _fail_key(user_id)}
    )
    return await locked_until(session, user_id, window)


async def clear_failures(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        text("DELETE FROM ops.rate_counters WHERE key IN (:fail, :lock)"),
        {"fail": _fail_key(user_id), "lock": _lock_key(user_id)},
    )


# Password reset (FR-ACC-3). Tokens live in identity.one_time_tokens as SHA-256 hashes.

RESET_PASSWORD = "reset_password"


async def get_account(session: AsyncSession, user_id: uuid.UUID) -> Account | None:
    row = (
        await session.execute(
            text(
                "SELECT id, email::text, password_hash, status FROM identity.users WHERE id = :id"
            ),
            {"id": user_id},
        )
    ).first()
    return Account(*row) if row else None


async def retire_reset_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Make every live, unused reset token of this learner expire now."""
    await session.execute(
        text("""
        UPDATE identity.one_time_tokens SET expires_at = now()
         WHERE user_id = :user_id AND purpose = :purpose
           AND used_at IS NULL AND expires_at > now()
        """),
        {"user_id": user_id, "purpose": RESET_PASSWORD},
    )


async def insert_reset_token(
    session: AsyncSession, user_id: uuid.UUID, token_hash: bytes, lifetime: timedelta
) -> None:
    await session.execute(
        text("""
        INSERT INTO identity.one_time_tokens (token_hash, user_id, purpose, expires_at)
        VALUES (:token_hash, :user_id, :purpose, now() + :lifetime)
        """),
        {
            "token_hash": token_hash,
            "user_id": user_id,
            "purpose": RESET_PASSWORD,
            "lifetime": lifetime,
        },
    )


async def consume_reset_token(session: AsyncSession, token_hash: bytes) -> uuid.UUID | None:
    """Mark a live reset token used and return its learner; None if unknown, used or expired."""
    user_id = await session.scalar(
        text("SELECT identity.consume_one_time_token(:token_hash, :purpose)"),
        {"token_hash": token_hash, "purpose": RESET_PASSWORD},
    )
    return uuid.UUID(str(user_id)) if user_id else None


async def delete_user_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """End every login session of a learner (row-level security needs the learner set)."""
    await session.execute(
        text("DELETE FROM identity.auth_sessions WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
