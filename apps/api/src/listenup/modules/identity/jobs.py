"""Background jobs of the identity module (ADR 0015, ADR 0017, ADR 0029)."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.identity import repository
from listenup.modules.identity.domain.tokens import new_token, reset_link, token_hash
from listenup.modules.notifications import service as notifications
from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, enqueue, job
from listenup.platform.storage import get_storage

logger = logging.getLogger(__name__)

SEND_PASSWORD_RESET = "identity.send_password_reset"
SEND_DELETION_NOTICE = "identity.send_deletion_notice"
PURGE_DUE_ACCOUNTS = "identity.purge_due_accounts"
PURGE_ACCOUNT = "identity.purge_account"

# How often the purge sweep looks for accounts whose grace period has ended (UTC).
PURGE_SCHEDULE = "*/15 * * * *"
# Requests queued per sweep; the next sweep takes the rest.
PURGE_BATCH = 100
# Deleting a learner's files is one storage call per thousand objects; a full library
# takes seconds, so half an hour means storage or the database is in trouble.
PURGE_TIMEOUT = timedelta(minutes=30)
PURGE_ATTEMPTS = 3
# A purge that gave up is queued again by the first sweep this long after it failed.
PURGE_RETRY_AFTER = timedelta(hours=1)


async def queue_password_reset(
    session: AsyncSession, user_id: uuid.UUID, *, in_grace_period: bool = False
) -> None:
    """Queue the reset email in the caller's transaction.

    While one is waiting, asking again queues nothing more, so repeated clicks send
    one email. A reset asked for during the grace period has its own key: a job queued
    before the deletion will send nothing, and must not swallow this one.
    """
    requested_at: datetime = await session.scalar(text("SELECT now()"))
    await enqueue(
        session,
        SEND_PASSWORD_RESET,
        unique_key=f"password_reset:{user_id}:{'grace' if in_grace_period else 'active'}",
        user_id=str(user_id),
        requested_at=requested_at.isoformat(),
    )


@job(Lane.BACKGROUND, SEND_PASSWORD_RESET)
async def send_password_reset(deps: JobDeps, user_id: str, requested_at: str | None = None) -> None:
    """Mint a reset token and email its link (FR-ACC-3).

    The token is created here, not in the request, so the raw token is never written
    anywhere, not even into the job queue: only the worker's memory and the email
    hold it. Each run retires older unused reset links before minting a new one, so
    a retried run leaves exactly one working link, the one in the email it sends.

    A reset asked for before the learner deleted the account sends nothing: deleting
    retires the links issued before it, and one minted afterwards would be a link
    issued before the deletion all the same (#120). A reset asked for during the grace
    period is sent; signing in afterwards still asks to restore the account.
    """
    settings = get_settings()
    learner = uuid.UUID(user_id)
    token = new_token()
    async with deps.database.transaction(learner) as session:
        account = await repository.get_account(session, learner)
        if account is None or account.gone:
            return  # the account went away after the request; nothing to send
        if account.waiting_for_deletion and requested_at is not None:
            deleted_at = await repository.deletion_requested_at(session, learner)
            if deleted_at is not None and deleted_at >= datetime.fromisoformat(requested_at):
                return
        await repository.retire_reset_tokens(session, learner)
        await repository.insert_reset_token(
            session,
            learner,
            token_hash(token),
            timedelta(minutes=settings.password_reset_minutes),
        )
    await notifications.send_password_reset(
        to=account.email,
        link=reset_link(settings.web_base_url, token),
        valid_minutes=settings.password_reset_minutes,
    )


def sign_in_link(web_base_url: str) -> str:
    return f"{web_base_url.rstrip('/')}/sign-in"


async def queue_deletion_notice(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Queue the deletion confirmation email in the caller's transaction."""
    await enqueue(
        session,
        SEND_DELETION_NOTICE,
        unique_key=f"deletion_notice:{user_id}",
        user_id=str(user_id),
    )


@job(Lane.BACKGROUND, SEND_DELETION_NOTICE)
async def send_deletion_notice(deps: JobDeps, user_id: str) -> None:
    """Email that the account is deleted and how to restore it (FR-ACC-4, D9).

    Nothing is sent when the learner restored the account before the job ran, or when
    it is already gone.
    """
    learner = uuid.UUID(user_id)
    async with deps.database.transaction() as session:
        account = await repository.get_account(session, learner)
    if account is None or not account.waiting_for_deletion:
        return
    assert account.deletion_scheduled_at is not None
    await notifications.send_account_deletion(
        to=account.email,
        deletion_at=account.deletion_scheduled_at,
        sign_in_link=sign_in_link(get_settings().web_base_url),
    )


@job(Lane.BACKGROUND, PURGE_DUE_ACCOUNTS, schedule=PURGE_SCHEDULE)
async def purge_due_accounts(deps: JobDeps, timestamp: int | None = None) -> int:
    """Queue a purge for every account whose grace period has ended (DR-1, D9).

    Runs on a schedule. Each request gets its own job, keyed by the request, so a
    request is never purged by two jobs at once and a failed purge is queued again
    by a later sweep. Returns how many purges it queued.
    """
    queued = 0
    async with deps.database.transaction() as session:
        due = await repository.due_deletion_requests(session, PURGE_BATCH, PURGE_RETRY_AFTER)
        for request_id in due:
            if await queue_purge(session, request_id) is not None:
                queued += 1
    return queued


async def queue_purge(session: AsyncSession, request_id: uuid.UUID) -> int | None:
    return await enqueue(
        session,
        PURGE_ACCOUNT,
        unique_key=f"purge_account:{request_id}",
        lock=f"deletion_request:{request_id}",
        request_id=str(request_id),
    )


async def _give_up_purge(deps: JobDeps, request_id: str) -> None:
    """The last attempt failed or timed out: mark the request 'failed', so a purge left
    half done shows, and the sweep queues it again after `PURGE_RETRY_AFTER`. The
    account stays unable to sign in or be restored meanwhile."""
    async with deps.database.transaction() as session:
        if await repository.mark_deletion_failed(session, uuid.UUID(request_id)):
            logger.error("account purge gave up; retried later", extra={"request": request_id})


@job(
    Lane.BACKGROUND,
    PURGE_ACCOUNT,
    timeout=PURGE_TIMEOUT,
    max_attempts=PURGE_ATTEMPTS,
    on_give_up=_give_up_purge,
)
async def purge_account(deps: JobDeps, request_id: str) -> dict[str, Any] | None:
    """Delete an account and everything it owns (FR-ACC-4, DR-1; Database Design 10.1).

    1. The account becomes 'deleting': no sign-in and no restore from here on.
    2. Storage first: every object under the learner's prefix, so a crash never
       leaves files that no row points to. The request becomes 'storage_deleted'.
    3. `DELETE FROM identity.users`: cascades remove every learner row, and the
       reference-count trigger releases shared media, which stays for other learners.
       The request becomes 'completed' with a report of rows and objects removed, in
       the same transaction.
    4. A last sweep of the prefix removes any file a job still running for the
       learner wrote after step 2.

    Idempotent: each step checks the request's state, deleting what is already gone
    is not an error, and a request that is not due, cancelled or completed is left
    alone. When the last attempt fails, the request becomes 'failed' and a later sweep
    runs it again from the storage step. Returns the report, or None when there was
    nothing to do.
    """
    request_uuid = uuid.UUID(request_id)
    storage = get_storage()
    async with deps.database.transaction() as session:
        request = await repository.lock_deletion_request(session, request_uuid)
        if request is None or request.status not in ("pending", "storage_deleted", "failed"):
            return None
        if not request.due:
            return None
        learner = request.subject_user_id
        status = await repository.lock_user_status(session, learner)
        if status == "active":
            # A restore always cancels the request in its own transaction, so this
            # should not happen; an active account is never purged.
            logger.error("deletion request of an active account", extra={"request": request_id})
            return None
        if status == "pending_deletion":
            await repository.mark_account_deleting(session, learner)
        if status is not None:
            await repository.delete_user_sessions(session, learner)
            current = await content.upload_media_ids(session, learner)
        else:
            current = []
        media = sorted(set(request.media_object_ids) | set(current), key=str)
        report: dict[str, Any] = dict(request.report or {})

    removed = 0
    for prefix in request.storage_prefixes:
        removed += await storage.delete_prefix(prefix)
    report["objects_removed"] = int(report.get("objects_removed", 0)) + removed
    report["media_objects"] = [str(m) for m in media]
    async with deps.database.transaction() as session:
        await repository.update_deletion_request(
            session, request_uuid, status="storage_deleted", report=report, media_object_ids=media
        )

    async with deps.database.transaction() as session:
        locked = await repository.lock_deletion_request(session, request_uuid)
        if locked is None or locked.status != "storage_deleted":
            return None  # another run finished it meanwhile
        rows: dict[str, int] = {}
        if await repository.lock_user_status(session, learner) is not None:
            rows = await repository.count_learner_rows(session, learner)
            await repository.delete_user(session, learner)
            # Sign-in counters are keyed by the id with no foreign key, so the cascade
            # misses them (DR-1).
            await repository.clear_failures(session, learner)
        report["rows_removed"] = rows
        report["rows_total"] = sum(rows.values())
        await repository.update_deletion_request(
            session, request_uuid, status="completed", report=report
        )

    late = 0
    for prefix in request.storage_prefixes:
        late += await storage.delete_prefix(prefix)
    if late:
        report["objects_removed"] += late
        async with deps.database.transaction() as session:
            await repository.update_deletion_request(
                session, request_uuid, status="completed", report=report
            )
    logger.info(
        "account purged",
        extra={
            "request": request_id,
            "rows_total": report["rows_total"],
            "objects_removed": report["objects_removed"],
        },
    )
    return report
