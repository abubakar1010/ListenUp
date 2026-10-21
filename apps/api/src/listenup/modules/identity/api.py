"""HTTP routes of the identity module (Architecture 9.2: Auth and Account)."""

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from listenup.modules.identity.domain.consents import ConsentKind, CurrentVersions
from listenup.modules.identity.service import AccountsDep, SignedInLearner, consent_versions
from listenup.platform.database import DbSession

router = APIRouter(tags=["identity"])


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class Registration(Credentials):
    terms_version: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "The terms of service version the learner accepted (#104); it must be the "
            "current one from GET /auth/consent-versions."
        ),
    )
    privacy_version: str | None = Field(
        default=None,
        max_length=20,
        description="The privacy policy version the learner accepted; it must be current.",
    )


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
    deletion_grace_days: int = Field(
        description="Days a deleted account can be restored before its data is removed."
    )
    consents_required: list[Literal["terms", "privacy"]] = Field(
        description=(
            "Documents whose current version the learner has not accepted yet (#104). "
            "Accept each with POST /me/consents before going on."
        )
    )


class ConsentVersions(BaseModel):
    terms: str
    privacy: str
    voice_recording: str

    @classmethod
    def of(cls, current: CurrentVersions) -> "ConsentVersions":
        return cls.model_validate(asdict(current))


@router.get("/auth/consent-versions")
async def current_consent_versions(request: Request) -> ConsentVersions:
    """The document versions a learner accepts now, for the sign-up form (#104)."""
    return ConsentVersions.of(consent_versions(request.app.state.settings))


@router.post("/auth/register", status_code=201)
async def register(
    body: Registration,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> Me:
    """Create an account. The learner must accept the current terms and privacy
    versions: 422 `consent_required` without them, 409 `consent_version_changed` when
    they changed meanwhile (#104)."""
    learner = await accounts.register(
        session,
        request,
        response,
        body.email,
        body.password,
        terms_version=body.terms_version,
        privacy_version=body.privacy_version,
    )
    return Me.model_validate(await accounts.profile(session, learner))


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
    return Me.model_validate(await accounts.profile(session, learner))


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: DbSession, accounts: AccountsDep
) -> None:
    await accounts.sign_out(session, request, response)


@router.get("/me")
async def me(learner: SignedInLearner, session: DbSession, accounts: AccountsDep) -> Me:
    return Me.model_validate(await accounts.profile(session, learner))


class ConsentRecord(BaseModel):
    kind: ConsentKind
    version: str
    granted_at: datetime
    withdrawn_at: datetime | None
    current: bool = Field(description="True when this is the version in force now.")


class Consents(BaseModel):
    current: ConsentVersions
    consents: list[ConsentRecord] = Field(description="Every version accepted, newest first.")


async def _consents(
    request: Request, session: DbSession, accounts: AccountsDep, learner: uuid.UUID
) -> Consents:
    current = consent_versions(request.app.state.settings)
    return Consents(
        current=ConsentVersions.of(current),
        consents=[
            ConsentRecord(
                kind=c.kind,
                version=c.version,
                granted_at=c.granted_at,
                withdrawn_at=c.withdrawn_at,
                current=c.version == current.of(c.kind),
            )
            for c in await accounts.consents(session, learner)
        ],
    )


@router.get("/me/consents")
async def my_consents(
    request: Request, learner: SignedInLearner, session: DbSession, accounts: AccountsDep
) -> Consents:
    """The learner's consents for the settings page (#104)."""
    return await _consents(request, session, accounts, learner)


class GrantConsent(BaseModel):
    kind: ConsentKind
    version: str = Field(min_length=1, max_length=20)


@router.post("/me/consents")
async def grant_consent(
    body: GrantConsent,
    request: Request,
    learner: SignedInLearner,
    session: DbSession,
    accounts: AccountsDep,
) -> Consents:
    """Accept the current version of a document (#104): a changed terms or privacy
    policy on sign-in, or voice recording before Shadow. A version that is not current
    answers 409 `consent_version_changed`. Granting again changes nothing."""
    await accounts.grant_consent(session, learner, body.kind, body.version)
    return await _consents(request, session, accounts, learner)


class WithdrawConsent(BaseModel):
    kind: ConsentKind


@router.post("/me/consents/withdraw")
async def withdraw_consent(
    body: WithdrawConsent,
    request: Request,
    learner: SignedInLearner,
    session: DbSession,
    accounts: AccountsDep,
) -> Consents:
    """Withdraw voice-recording consent (FR-SH-17): sets `withdrawn_at`, and new Shadow
    rounds are refused until the learner agrees again. Terms and privacy answer 409
    `consent_not_withdrawable`."""
    await accounts.withdraw_consent(session, learner, body.kind)
    return await _consents(request, session, accounts, learner)


class DeletionSummary(BaseModel):
    clips: int = Field(ge=0)
    practice_sessions: int = Field(ge=0)
    cards: int = Field(ge=0)
    recordings: int = Field(ge=0)


@router.get("/me/deletion-summary")
async def deletion_summary(
    learner: SignedInLearner, session: DbSession, accounts: AccountsDep
) -> DeletionSummary:
    """Counts for the review step before account deletion (UX-06)."""
    return DeletionSummary.model_validate(await accounts.deletion_summary(session, learner))


class DeleteAccount(BaseModel):
    password: str = Field(
        default="",
        max_length=1000,
        description="Current password, or a fresh Google confirmation cookie.",
    )
    confirm: Literal[True] = Field(description="Must be true: the learner confirmed.")


class DeletionScheduled(BaseModel):
    deletion_scheduled_at: datetime
    detail: str


@router.delete("/me", status_code=202)
async def delete_me(
    body: DeleteAccount,
    request: Request,
    learner: SignedInLearner,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> DeletionScheduled:
    """Delete the account (FR-ACC-4, DR-1, D9; ADR 0029).

    The account is disabled at once and every login session ends. Everything is
    deleted when the grace period ends, unless the learner signs in and restores the
    account before then.
    """
    verified = (
        await request.app.state.google.deletion_proof(request, learner)
        if not body.password
        else False
    )
    until = await accounts.delete_account(
        session, response, learner, body.password, google_verified=verified
    )
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
