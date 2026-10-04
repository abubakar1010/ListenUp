"""HTTP routes of the identity module (Architecture 9.2: Auth and Account)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from listenup.modules.identity import service
from listenup.modules.identity.service import AccountsDep, CurrentLearner
from listenup.platform.database import DbSession

router = APIRouter(tags=["identity"])


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class SignIn(Credentials):
    restore: bool = Field(
        default=False,
        description=(
            "Restore an account waiting for deletion (#120). Without it, signing in to "
            "such an account answers 409 account_pending_deletion with the date."
        ),
    )


class Me(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool


@router.post("/auth/register", status_code=201)
async def register(
    body: Credentials,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> Me:
    learner = await accounts.register(session, request, response, body.email, body.password)
    return Me.model_validate(await service.get_profile(session, learner))


@router.post("/auth/login")
async def login(
    body: SignIn,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> Me:
    """Sign in. An account deleted less than the grace period ago answers 409
    `account_pending_deletion` (with `deletion_scheduled_at`) until the learner sends
    `restore: true`, which cancels the deletion (#120)."""
    learner = await accounts.sign_in(
        session, request, response, body.email, body.password, restore=body.restore
    )
    return Me.model_validate(await service.get_profile(session, learner))


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: DbSession, accounts: AccountsDep
) -> None:
    await accounts.sign_out(session, request, response)


@router.get("/me")
async def me(learner: CurrentLearner, session: DbSession) -> Me:
    return Me.model_validate(await service.get_profile(session, learner))


class DeleteAccount(BaseModel):
    password: str = Field(max_length=1000, description="The current password, asked again.")
    confirm: Literal[True] = Field(description="Must be true: the learner confirmed.")


class DeletionScheduled(BaseModel):
    deletion_scheduled_at: datetime
    detail: str


@router.delete("/me", status_code=202)
async def delete_me(
    body: DeleteAccount,
    learner: CurrentLearner,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> DeletionScheduled:
    """Delete the account (FR-ACC-4, DR-1, D9; ADR 0029).

    The account is disabled at once and every login session ends. Everything is
    deleted when the grace period ends, unless the learner signs in and restores the
    account before then.
    """
    until = await accounts.delete_account(session, response, learner, body.password)
    return DeletionScheduled(
        deletion_scheduled_at=until,
        detail=(
            "Your account is deleted and you are signed out everywhere. To get it back "
            "with everything in it, sign in before the date shown."
        ),
    )


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=320)


class PasswordResetRequested(BaseModel):
    detail: str


class PasswordReset(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=1000)


RESET_REQUESTED = (
    "If an account uses this email, we have sent it a link to reset the password. "
    "The link works once. Check your inbox and spam folder."
)


@router.post("/auth/password-reset", status_code=202)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    session: DbSession,
    accounts: AccountsDep,
) -> PasswordResetRequested:
    """Email a reset link. The answer is the same whether or not the email has an account."""
    await accounts.request_password_reset(session, request, body.email)
    return PasswordResetRequested(detail=RESET_REQUESTED)


@router.post("/auth/password-reset/confirm", status_code=204)
async def reset_password(
    body: PasswordReset,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> None:
    """Set a new password with the token from the email; signs the learner out everywhere."""
    await accounts.reset_password(session, request, response, body.token, body.password)
