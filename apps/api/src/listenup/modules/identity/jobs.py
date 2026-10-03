"""Background jobs of the identity module (ADR 0015, ADR 0017)."""

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.identity import repository
from listenup.modules.identity.domain.tokens import new_token, reset_link, token_hash
from listenup.modules.notifications import service as notifications
from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, enqueue, job

SEND_PASSWORD_RESET = "identity.send_password_reset"


async def queue_password_reset(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Queue the reset email in the caller's transaction.

    While one is waiting, asking again queues nothing more, so repeated clicks send
    one email.
    """
    await enqueue(
        session,
        SEND_PASSWORD_RESET,
        unique_key=f"password_reset:{user_id}",
        user_id=str(user_id),
    )


@job(Lane.BACKGROUND, SEND_PASSWORD_RESET)
async def send_password_reset(deps: JobDeps, user_id: str) -> None:
    """Mint a reset token and email its link (FR-ACC-3).

    The token is created here, not in the request, so the raw token is never written
    anywhere, not even into the job queue: only the worker's memory and the email
    hold it. Each run retires older unused reset links before minting a new one, so
    a retried run leaves exactly one working link, the one in the email it sends.
    """
    settings = get_settings()
    learner = uuid.UUID(user_id)
    token = new_token()
    async with deps.database.transaction(learner) as session:
        account = await repository.get_account(session, learner)
        if account is None or account.status == "deleting":
            return  # the account went away after the request; nothing to send
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
