"""Accounts, sign-in and password reset (FR-ACC-1, FR-ACC-2, FR-ACC-3, NFR-SEC-1, D17).

The public face of the identity module: other modules use `CurrentLearner` to require
a signed-in learner and get their id, with row-level security already scoped to them.
"""

import hashlib
import ipaddress
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.identity import jobs, passwords, repository
from listenup.modules.identity.domain.credentials import (
    email_problem,
    normalize_email,
    password_problem,
)
from listenup.modules.identity.domain.tokens import new_token, token_hash
from listenup.platform.config import Settings, get_settings
from listenup.platform.database import Database, DbSession, set_learner
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7
from listenup.platform.rate_limit import Limit, RateLimiter, ip_key


def session_cookie_name(secure: bool) -> str:
    return "__Host-listenup_session" if secure else "listenup_session"


def _client_ip(request: Request) -> str | None:
    """The caller's address, or None when the server did not get a real IP."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def _not_signed_in() -> ProblemError:
    return ProblemError(401, "not_signed_in", "Sign in to continue.")


async def current_learner(request: Request, session: DbSession) -> uuid.UUID:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(session_cookie_name(settings.cookies_secure))
    if not token:
        raise _not_signed_in()
    learner = await repository.resolve_auth_session(session, token_hash(token))
    if learner is None:
        raise _not_signed_in()
    await set_learner(session, learner)
    return learner


CurrentLearner = Annotated[uuid.UUID, Depends(current_learner)]


class Accounts:
    def __init__(self, settings: Settings, database: Database, limiter: RateLimiter) -> None:
        self.settings = settings
        self.database = database
        self.limiter = limiter
        self.lock = timedelta(minutes=settings.login_lock_minutes)
        self.login_by_ip = Limit(
            "login",
            settings.login_ip_limit,
            timedelta(minutes=settings.login_ip_window_minutes),
        )
        self.register_by_ip = Limit("register", settings.register_ip_limit, timedelta(hours=1))
        hour = timedelta(hours=1)
        self.reset_request_by_ip = Limit("password_reset", settings.password_reset_ip_limit, hour)
        self.reset_request_by_email = Limit(
            "password_reset", settings.password_reset_email_limit, hour
        )
        self.reset_by_ip = Limit("password_reset_confirm", settings.password_reset_ip_limit, hour)

    async def register(
        self,
        session: AsyncSession,
        request: Request,
        response: Response,
        email: str,
        password: str,
    ) -> uuid.UUID:
        ip = _client_ip(request)
        if ip:
            await self.limiter.enforce(self.register_by_ip, ip_key(self.register_by_ip, ip))
        email = normalize_email(email)
        if problem := email_problem(email):
            raise ProblemError(422, "invalid_email", problem)
        if problem := password_problem(password):
            raise ProblemError(422, "weak_password", problem)

        user_id = uuid7()
        if not await repository.insert_user(
            session, user_id, email, await passwords.hash_password(password)
        ):
            raise ProblemError(
                409,
                "email_taken",
                "An account with this email already exists. Sign in instead.",
            )
        await self._start_session(session, request, response, user_id)
        return user_id

    async def sign_in(
        self,
        session: AsyncSession,
        request: Request,
        response: Response,
        email: str,
        password: str,
    ) -> uuid.UUID:
        ip = _client_ip(request)
        if ip:
            # Counts every attempt from this IP, across all accounts.
            await self.limiter.enforce(self.login_by_ip, ip_key(self.login_by_ip, ip))

        account = await repository.find_account(session, normalize_email(email))
        if account is not None and account.status != "deleting":
            async with self.database.transaction() as own:
                until = await repository.locked_until(own, account.id, self.lock)
            if until is not None:
                raise self._locked(until)

        valid = await passwords.verify_password(
            account.password_hash if account else None, password
        )
        if account is None or not valid or account.status == "deleting":
            if account is not None and account.status != "deleting":
                # Committed on its own: this request is about to be refused and rolled back.
                async with self.database.transaction() as own:
                    until = await repository.record_failure(
                        own, account.id, self.lock, self.settings.login_lock_threshold
                    )
                if until is not None:
                    raise self._locked(until)
            raise ProblemError(
                401,
                "invalid_credentials",
                "The email or password is wrong. Check both and try again.",
            )

        async with self.database.transaction() as own:
            await repository.clear_failures(own, account.id)
        if account.password_hash and passwords.needs_rehash(account.password_hash):
            await repository.update_password_hash(
                session, account.id, await passwords.hash_password(password)
            )
        await repository.restore_account(session, account.id)
        await self._start_session(session, request, response, account.id)
        return account.id

    async def request_password_reset(
        self, session: AsyncSession, request: Request, email: str
    ) -> None:
        """Queue a reset email if the address has an account (FR-ACC-3).

        The caller always gets the same answer, so it cannot learn which emails are
        registered. Past the per-address limit the request is dropped silently rather
        than refused, so nobody can use the limit to probe for accounts or to stop a
        learner from receiving their own reset email with a 429.
        """
        ip = _client_ip(request)
        if ip:
            await self.limiter.enforce(
                self.reset_request_by_ip, ip_key(self.reset_request_by_ip, ip)
            )
        email = normalize_email(email)
        if problem := email_problem(email):
            raise ProblemError(422, "invalid_email", problem)
        address = hashlib.sha256(email.casefold().encode()).hexdigest()
        hit = await self.limiter.hit(
            self.reset_request_by_email, f"{self.reset_request_by_email.name}:email:{address}"
        )
        if not hit.allowed:
            return
        account = await repository.find_account(session, email)
        if account is not None and account.status != "deleting":
            await jobs.queue_password_reset(session, account.id)

    async def reset_password(
        self,
        session: AsyncSession,
        request: Request,
        response: Response,
        token: str,
        password: str,
    ) -> None:
        """Set a new password with an emailed token (FR-ACC-3).

        The token works once. Every login session of the learner ends, including the
        caller's, and the sign-in lockout is lifted, so the new password works at once.
        """
        ip = _client_ip(request)
        if ip:
            await self.limiter.enforce(self.reset_by_ip, ip_key(self.reset_by_ip, ip))
        if problem := password_problem(password):
            raise ProblemError(422, "weak_password", problem)
        learner = await repository.consume_reset_token(session, token_hash(token))
        account = await repository.get_account(session, learner) if learner else None
        if learner is None or account is None or account.status == "deleting":
            raise ProblemError(
                400,
                "invalid_reset_link",
                "This reset link has expired or was already used. "
                "Ask for a new link from the sign-in page.",
            )
        await set_learner(session, learner)
        await repository.update_password_hash(
            session, learner, await passwords.hash_password(password)
        )
        await repository.retire_reset_tokens(session, learner)
        await repository.delete_user_sessions(session, learner)
        await repository.clear_failures(session, learner)
        self._clear_cookie(response)

    async def sign_out(self, session: AsyncSession, request: Request, response: Response) -> None:
        name = session_cookie_name(self.settings.cookies_secure)
        token = request.cookies.get(name)
        if token:
            await _revoke(session, token)
        self._clear_cookie(response)

    def _clear_cookie(self, response: Response) -> None:
        response.delete_cookie(
            session_cookie_name(self.settings.cookies_secure),
            path="/",
            secure=self.settings.cookies_secure,
            httponly=True,
            samesite="lax",
        )

    async def _start_session(
        self, session: AsyncSession, request: Request, response: Response, user_id: uuid.UUID
    ) -> None:
        name = session_cookie_name(self.settings.cookies_secure)
        # Rotation: a sign-in always gets a new token, and the one the browser had
        # before (if any) stops working, so a planted session id is useless.
        if old := request.cookies.get(name):
            await _revoke(session, old)
        await set_learner(session, user_id)
        token = new_token()
        lifetime = timedelta(days=self.settings.session_days)
        await repository.create_auth_session(
            session,
            session_id=uuid7(),
            user_id=user_id,
            token_hash=token_hash(token),
            lifetime=lifetime,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
        response.set_cookie(
            name,
            token,
            max_age=int(lifetime.total_seconds()),
            path="/",
            secure=self.settings.cookies_secure,
            httponly=True,
            samesite="lax",
        )

    def _locked(self, until: datetime) -> ProblemError:
        seconds = max(1, int((until - _now(until)).total_seconds()) + 1)
        return ProblemError(
            429,
            "account_locked",
            "Too many failed sign-in attempts for this account. "
            "Wait until the time shown, then try again, or reset your password.",
            headers={"Retry-After": str(seconds)},
            locked_until=until.isoformat(),
        )


async def _revoke(session: AsyncSession, token: str) -> None:
    """End the login session behind a cookie, whoever it belongs to.

    Row-level security hides a login session until its learner is set, so the
    learner is looked up first; otherwise the delete would silently match nothing.
    """
    hashed = token_hash(token)
    owner = await repository.resolve_auth_session(session, hashed)
    if owner is not None:
        await set_learner(session, owner)
        await repository.delete_auth_session(session, hashed)


def _now(reference: datetime) -> datetime:
    return datetime.now(reference.tzinfo)


def get_accounts(request: Request) -> Accounts:
    accounts: Accounts = request.app.state.accounts
    return accounts


def build_accounts(
    database: Database, limiter: RateLimiter, settings: Settings | None = None
) -> Accounts:
    return Accounts(settings or get_settings(), database, limiter)


async def get_profile(session: AsyncSession, learner: uuid.UUID) -> dict[str, object]:
    profile = await repository.get_profile(session, learner)
    if profile is None:
        raise ProblemError(401, "not_signed_in", "Sign in to continue.")
    return profile


AccountsDep = Annotated[Accounts, Depends(get_accounts)]
