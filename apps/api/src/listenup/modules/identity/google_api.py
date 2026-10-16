"""Google sign-in, explicit restoration, and fresh deletion confirmation (FR-ACC-1/4)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.responses import RedirectResponse

from listenup.modules.identity import repository
from listenup.modules.identity.api import Me
from listenup.modules.identity.domain.credentials import normalize_email
from listenup.modules.identity.oidc import GoogleOIDC
from listenup.modules.identity.service import AccountsDep, current_learner
from listenup.platform.database import DbSession
from listenup.platform.errors import ProblemError

router = APIRouter(tags=["identity"])
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@router.get("/auth/oidc/google/start", status_code=303, response_class=RedirectResponse)
async def start(
    request: Request,
    session: DbSession,
    accounts: AccountsDep,
    next: str = "/library",
    purpose: Literal["login", "reauth"] = "login",
) -> Response:
    google: GoogleOIDC = request.app.state.google
    learner = await current_learner(request, session) if purpose == "reauth" else None
    await accounts.enforce_google_limit(request)
    return await google.start(request, next, learner)


@router.get("/auth/oidc/google/callback", status_code=303, response_class=RedirectResponse)
async def callback(
    request: Request,
    session: DbSession,
    accounts: AccountsDep,
    state: str = "",
    code: str = "",
    error: str = "",
) -> Response:
    google: GoogleOIDC = request.app.state.google
    flow = await google.take(request, state, "login")
    if error:
        path = (
            "/settings/delete-account?google=cancelled"
            if flow.get("user")
            else "/sign-in?google=cancelled"
        )
        return RedirectResponse(path, status_code=303, headers=HEADERS)
    claims = await google.claims(code, flow)
    if flow.get("user"):
        learner = await current_learner(request, session)
        linked = await repository.google_user_id(session, claims["sub"])
        if (
            str(learner) != flow["user"]
            or linked != learner
            or google.session_hash(request) != flow["session"]
        ):
            raise ProblemError(
                403, "google_account_mismatch", "Choose the Google account linked to this account."
            )
        proof = await google.put(
            request.cookies[google.cookie_name()],
            "delete",
            {"user": str(learner), "session": flow["session"]},
            learner,
        )
        response = RedirectResponse(
            "/settings/delete-account?google=confirmed", status_code=303, headers=HEADERS
        )
        google.cookie(response, proof, "_delete")
        return response
    account = await repository.google_account(
        session, claims["sub"], normalize_email(claims["email"])
    )
    if account.gone:
        raise ProblemError(401, "invalid_credentials", "This account cannot sign in.")
    response = RedirectResponse(flow["next"], status_code=303, headers=HEADERS)
    try:
        await accounts.complete_sign_in(session, request, response, account, restore=False)
    except ProblemError as problem:
        if problem.code != "account_pending_deletion":
            raise
        proof = await google.put(
            request.cookies[google.cookie_name()],
            "restore",
            {"user": str(account.id), "next": flow["next"]},
            account.id,
        )
        response = RedirectResponse("/sign-in?google=restore", status_code=303, headers=HEADERS)
        await accounts.sign_out(session, request, response)
        google.cookie(response, proof, "_restore")
    return response


async def restore_account(
    request: Request, session: DbSession, *, consume: bool
) -> tuple[repository.Account, dict[str, object]]:
    google: GoogleOIDC = request.app.state.google
    flow = await google.take(
        request, request.cookies.get(google.cookie_name("_restore"), ""), "restore", consume=consume
    )
    account = await repository.get_account(session, uuid.UUID(flow["user"]))
    if account is None or account.gone:
        raise ProblemError(401, "invalid_credentials", "This account cannot sign in.")
    return account, flow


class PendingRestore(BaseModel):
    deletion_scheduled_at: str
    next_path: str


@router.get("/auth/oidc/google/restore")
async def pending_restore(
    request: Request, session: DbSession, response: Response
) -> PendingRestore:
    response.headers.update(HEADERS)
    account, flow = await restore_account(request, session, consume=False)
    if not account.waiting_for_deletion:
        raise ProblemError(400, "google_auth_failed", "Start Google sign-in again.")
    assert account.deletion_scheduled_at is not None
    return PendingRestore(
        deletion_scheduled_at=account.deletion_scheduled_at.isoformat(), next_path=str(flow["next"])
    )


class RestoreGoogle(BaseModel):
    restore: bool


@router.post(
    "/auth/oidc/google/restore", responses={204: {"description": "Kept deleted; signed out."}}
)
async def restore(
    body: RestoreGoogle,
    request: Request,
    session: DbSession,
    response: Response,
    accounts: AccountsDep,
) -> Me | None:
    response.headers.update(HEADERS)
    account, _ = await restore_account(request, session, consume=True)
    if not body.restore:
        await accounts.sign_out(session, request, response)
        response.status_code = 204
        return None
    await accounts.complete_sign_in(session, request, response, account, restore=True)
    return Me.model_validate(await accounts.profile(session, account.id))
