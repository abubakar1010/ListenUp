"""SQL for the identity module."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    email: str
    password_hash: str | None
    status: str
    # End of the grace period while the account waits for deletion (D9), else None.
    deletion_scheduled_at: datetime | None
    # Deleted for good, or its grace period is over: it behaves as if it did not exist.
    gone: bool

    @property
    def waiting_for_deletion(self) -> bool:
        """Deleted, but the learner can still restore it by signing in."""
        return self.status == "pending_deletion" and not self.gone


_ACCOUNT_COLUMNS = """
    id, email::text, password_hash, status, deletion_scheduled_at,
    status = 'deleting' OR (status = 'pending_deletion' AND deletion_scheduled_at <= now())
"""


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
            text(f"SELECT {_ACCOUNT_COLUMNS} FROM identity.users WHERE email = :email"),
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


async def schedule_deletion(
    session: AsyncSession, user_id: uuid.UUID, grace: timedelta
) -> datetime | None:
    """Disable an active account until its purge (D9); returns when the grace period ends."""
    result: datetime | None = await session.scalar(
        text("""
        UPDATE identity.users
           SET status = 'pending_deletion', deletion_scheduled_at = now() + :grace
         WHERE id = :id AND status = 'active'
        RETURNING deletion_scheduled_at
        """),
        {"id": user_id, "grace": grace},
    )
    return result


async def restore_account(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Reactivate an account whose grace period has not ended (#120).

    False when there is nothing to restore: the grace period ended, or the purge job
    already took the account (it sets 'deleting' first, under the same row lock).
    """
    restored = await session.scalar(
        text("""
        UPDATE identity.users SET status = 'active', deletion_scheduled_at = NULL
         WHERE id = :id AND status = 'pending_deletion' AND deletion_scheduled_at > now()
        RETURNING id
        """),
        {"id": user_id},
    )
    return restored is not None


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
            text(f"SELECT {_ACCOUNT_COLUMNS} FROM identity.users WHERE id = :id"),
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


# Account deletion (FR-ACC-4, DR-1, D9; ADR 0029). ops.deletion_requests is the audit
# record of each deletion; the API writes and cancels it, the purge job completes it.

ACCOUNT_SCOPE = "account"


def storage_prefix(user_id: uuid.UUID) -> str:
    """Every stored file of a learner lives under this prefix (Architecture 8.1)."""
    return f"users/{user_id}/"


async def insert_deletion_request(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    due_at: datetime,
    media_object_ids: list[uuid.UUID],
) -> None:
    await session.execute(
        text("""
        INSERT INTO ops.deletion_requests
          (id, subject_user_id, scope, storage_prefixes, media_object_ids, due_at)
        VALUES (:id, :user_id, :scope, ARRAY[:prefix], CAST(:media AS uuid[]), :due_at)
        """),
        {
            "id": request_id,
            "user_id": user_id,
            "scope": ACCOUNT_SCOPE,
            "prefix": storage_prefix(user_id),
            "media": [str(media) for media in media_object_ids],
            "due_at": due_at,
        },
    )


async def cancel_deletion_requests(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Cancel the learner's open account deletion (a restore); returns how many."""
    result = await session.execute(
        text("""
        UPDATE ops.deletion_requests SET status = 'cancelled', cancelled_at = now()
         WHERE subject_user_id = :user_id AND scope = :scope AND status = 'pending'
        """),
        {"user_id": user_id, "scope": ACCOUNT_SCOPE},
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True)
class DeletionRequest:
    id: uuid.UUID
    subject_user_id: uuid.UUID
    status: str
    storage_prefixes: list[str]
    media_object_ids: list[uuid.UUID]
    report: dict[str, Any] | None
    due: bool  # the grace period has ended


async def due_deletion_requests(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Open account requests whose grace period has ended, oldest due first."""
    rows = await session.execute(
        text("""
        SELECT id FROM ops.deletion_requests
         WHERE status IN ('pending', 'storage_deleted') AND due_at <= now() AND scope = :scope
         ORDER BY due_at, id
         LIMIT :limit
        """),
        {"scope": ACCOUNT_SCOPE, "limit": limit},
    )
    return [row.id for row in rows]


async def lock_deletion_request(
    session: AsyncSession, request_id: uuid.UUID
) -> DeletionRequest | None:
    row = (
        await session.execute(
            text("""
            SELECT id, subject_user_id, status, storage_prefixes, media_object_ids, report,
                   due_at <= now()
              FROM ops.deletion_requests WHERE id = :id AND scope = :scope
               FOR UPDATE
            """),
            {"id": request_id, "scope": ACCOUNT_SCOPE},
        )
    ).first()
    if row is None:
        return None
    return DeletionRequest(
        id=row[0],
        subject_user_id=row[1],
        status=row[2],
        storage_prefixes=list(row[3]),
        media_object_ids=[uuid.UUID(str(media)) for media in row[4]],
        report=row[5],
        due=bool(row[6]),
    )


async def lock_user_status(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    status: str | None = await session.scalar(
        text("SELECT status FROM identity.users WHERE id = :id FOR UPDATE"), {"id": user_id}
    )
    return status


async def mark_account_deleting(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Past the grace period: no sign-in, no restore, from here on (Database Design 10.1)."""
    await session.execute(
        text("""
        UPDATE identity.users SET status = 'deleting', deletion_scheduled_at = NULL
         WHERE id = :id AND status = 'pending_deletion'
        """),
        {"id": user_id},
    )


async def update_deletion_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    status: str,
    report: dict[str, Any],
    media_object_ids: list[uuid.UUID] | None = None,
) -> None:
    await session.execute(
        text("""
        UPDATE ops.deletion_requests
           SET status = :status, report = CAST(:report AS jsonb),
               media_object_ids = coalesce(CAST(:media AS uuid[]), media_object_ids),
               completed_at = CASE WHEN :status = 'completed' THEN coalesce(completed_at, now()) END
         WHERE id = :id
        """),
        {
            "id": request_id,
            "status": status,
            "report": json.dumps(report),
            "media": None if media_object_ids is None else [str(m) for m in media_object_ids],
        },
    )


async def count_learner_rows(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Rows of the learner in every application table, by table (for the purge report).

    Found from the catalog, so a table added later is counted without changing this:
    every learner-owned table has `user_id` (Database Design 2), and uploaded media
    has `uploaded_by`.
    """
    columns = await session.execute(
        text("""
        SELECT c.table_schema, c.table_name, c.column_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE t.table_type = 'BASE TABLE' AND c.column_name IN ('user_id', 'uploaded_by')
           AND c.table_schema IN ('identity', 'content', 'practice', 'grading', 'ops')
         ORDER BY 1, 2, 3
        """)
    )
    counts: dict[str, int] = {"identity.users": 1}
    for schema, table, column in columns:
        # Names come from the catalog, never from input; quoted all the same.
        found = await session.scalar(
            text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE "{column}" = :id'),
            {"id": user_id},
        )
        if found:
            counts[f"{schema}.{table}"] = int(found)
    return counts


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Delete the account; cascades remove every learner row (Database Design 10.1)."""
    deleted = await session.scalar(
        text("DELETE FROM identity.users WHERE id = :id AND status = 'deleting' RETURNING id"),
        {"id": user_id},
    )
    return deleted is not None
