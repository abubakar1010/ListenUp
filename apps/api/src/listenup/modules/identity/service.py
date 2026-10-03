"""Accounts and sign-in (FR-ACC-1, FR-ACC-2, NFR-SEC-1, D17).

The public face of the identity module: other modules use `CurrentLearner` to require
a signed-in learner and get their id, with row-level security already scoped to them.
"""

import hashlib
import ipaddress
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.identity import passwords, repository
from listenup.modules.identity.domain.credentials import (
    email_problem,
    normalize_email,
    password_problem,
)
from listenup.platform.config import Settings, get_settings
from listenup.platform.database import Database, DbSession, set_learner
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7
from listenup.platform.rate_limit import Limit, RateLimiter, ip_key


def session_cookie_name(secure: bool) -> str:
    return "__Host-listenup_session" if secure else "listenup_session"


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


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
    learner = await repository.resolve_auth_session(session, _token_hash(token))
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

    async def sign_out(self, session: AsyncSession, request: Request, response: Response) -> None:
        name = session_cookie_name(self.settings.cookies_secure)
        token = request.cookies.get(name)
        if token:
            await _revoke(session, token)
        response.delete_cookie(
            name, path="/", secure=self.settings.cookies_secure, httponly=True, samesite="lax"
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
        token = secrets.token_urlsafe(32)
        lifetime = timedelta(days=self.settings.session_days)
        await repository.create_auth_session(
            session,
            session_id=uuid7(),
            user_id=user_id,
            token_hash=_token_hash(token),
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
    token_hash = _token_hash(token)
    owner = await repository.resolve_auth_session(session, token_hash)
    if owner is not None:
        await set_learner(session, owner)
        await repository.delete_auth_session(session, token_hash)


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
