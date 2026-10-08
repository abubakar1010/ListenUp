"""Accounts, sign-in, password reset and deletion (FR-ACC-1 to FR-ACC-4, NFR-SEC-1, D9, D17).

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
from listenup.modules.identity.repository import Account
from listenup.platform.config import Settings, get_settings
from listenup.platform.database import Database, DbSession, set_learner
from listenup.platform.errors import ProblemError
from listenup.platform.events import EventType, publish
from listenup.platform.export import ExportPart, learner_rows
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


def _invalid_credentials() -> ProblemError:
    return ProblemError(
        401,
        "invalid_credentials",
        "The email or password is wrong. Check both and try again.",
    )


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
        await repository.release_email_of_gone_account(session, email)
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
        restore: bool = False,
    ) -> uuid.UUID:
        ip = _client_ip(request)
        if ip:
            # Counts every attempt from this IP, across all accounts.
            await self.limiter.enforce(self.login_by_ip, ip_key(self.login_by_ip, ip))

        account = await repository.find_account(session, normalize_email(email))
        valid = await self._check_password(account, password)
        # A deleted account past its grace period answers exactly like an unknown one.
        if account is None or not valid or account.gone:
            raise _invalid_credentials()

        async with self.database.transaction() as own:
            await repository.clear_failures(own, account.id)
        if account.password_hash and passwords.needs_rehash(account.password_hash):
            await repository.update_password_hash(
                session, account.id, await passwords.hash_password(password)
            )
        await self.complete_sign_in(session, request, response, account, restore=restore)
        return account.id

    async def _check_password(self, account: Account | None, password: str) -> bool:
        """Verify a password under the sign-in lockout (D17); True when it is right.

        A locked account answers 429 `account_locked` before the password is checked,
        and a wrong password counts as a failure, answering 429 when it locks the
        account. Both are committed on their own, since the caller is about to refuse
        the request and roll it back. A missing or gone account still costs a hash
        check, so the answer takes as long, and nothing is counted for it.
        """
        counted = account if account is not None and not account.gone else None
        if counted is not None:
            async with self.database.transaction() as own:
                until = await repository.locked_until(own, counted.id, self.lock)
            if until is not None:
                raise self._locked(until)
        valid = await passwords.verify_password(
            account.password_hash if account else None, password
        )
        if counted is not None and not valid:
            async with self.database.transaction() as own:
                until = await repository.record_failure(
                    own, counted.id, self.lock, self.settings.login_lock_threshold
                )
            if until is not None:
                raise self._locked(until)
        return valid

    async def complete_sign_in(
        self,
        session: AsyncSession,
        request: Request,
        response: Response,
        account: Account,
        *,
        restore: bool,
    ) -> None:
        """Start a login session for an account whose owner has just proved who they are.

        Every way of signing in ends here: email and password today, and Google
        sign-in (#32) once it is built, so the restore step (#120) applies to both.
        An account waiting for deletion (D9) is never signed in silently: without
        `restore` the caller gets 409 `account_pending_deletion` with the date the
        data will be deleted, and nothing changes, so declining leaves the learner
        signed out with the deletion still scheduled. With `restore` the deletion
        request is cancelled and the account is active again, with all its data.
        """
        if account.waiting_for_deletion:
            assert account.deletion_scheduled_at is not None
            if not restore:
                raise ProblemError(
                    409,
                    "account_pending_deletion",
                    "This account was deleted and is waiting to be removed. "
                    "Restore it to sign in, or leave it to be deleted.",
                    deletion_scheduled_at=account.deletion_scheduled_at.isoformat(),
                )
            await set_learner(session, account.id)
            # The request row is locked before the users row, the order the purge uses,
            # so the two cannot wait for each other. If the account cannot be restored
            # after all, the refusal rolls the cancellation back with the request.
            await repository.cancel_deletion_requests(session, account.id)
            if not await repository.restore_account(session, account.id):
                # The grace period ended between the lookup and now.
                raise _invalid_credentials()
        await self._start_session(session, request, response, account.id)

    async def delete_account(
        self,
        session: AsyncSession,
        response: Response,
        learner: uuid.UUID,
        password: str,
    ) -> datetime:
        """Delete the signed-in learner's account (FR-ACC-4, DR-1, D9; ADR 0029).

        The account is disabled at once: it waits as 'pending_deletion' for the grace
        period, every login session and unused reset link ends, open event streams
        close, and an `ops.deletion_requests` row records what the purge job will
        remove and when. Returns when the grace period ends.
        """
        account = await repository.get_account(session, learner)
        if account is None or account.status != "active":
            raise _not_signed_in()
        await self._reauthenticate(account, password)

        grace = timedelta(days=self.settings.account_deletion_grace_days)
        until = await repository.schedule_deletion(session, learner, grace)
        if until is None:
            raise _not_signed_in()  # deleted by a parallel request
        await repository.insert_deletion_request(
            session, request_id=uuid7(), user_id=learner, due_at=until
        )
        await repository.retire_reset_tokens(session, learner)
        await repository.delete_user_sessions(session, learner)
        await publish(session, learner, EventType.ACCOUNT_DISABLED, learner)
        await jobs.queue_deletion_notice(session, learner)
        self._clear_cookie(response)
        return until

    async def _reauthenticate(self, account: Account, password: str) -> None:
        """Ask for the password again before an irreversible change (NFR-SEC-5).

        Wrong passwords count towards the sign-in lockout (D17), so a stolen session
        cannot be used to guess the password. Accounts without a password (Google
        sign-in, #32, not built yet) will re-authenticate with Google instead.
        """
        if account.password_hash is None:
            raise ProblemError(
                409,
                "reauthentication_unavailable",
                "This account signs in with Google, and confirming with Google is not "
                "available yet. Contact support to delete the account.",
            )
        if not await self._check_password(account, password):
            raise ProblemError(
                403,
                "wrong_password",
                "The password is wrong. Enter the password you use to sign in.",
            )

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
        # An account waiting for deletion may reset its password (the learner may need
        # it to restore the account); signing in afterwards still asks to restore.
        if account is not None and not account.gone:
            await jobs.queue_password_reset(
                session, account.id, in_grace_period=account.waiting_for_deletion
            )

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
        Deleting the account retires its unused links; a reset during the grace period
        starts no session, so the data stays out of reach until the learner signs in
        and confirms the restore (#120).
        """
        ip = _client_ip(request)
        if ip:
            await self.limiter.enforce(self.reset_by_ip, ip_key(self.reset_by_ip, ip))
        if problem := password_problem(password):
            raise ProblemError(422, "weak_password", problem)
        learner = await repository.consume_reset_token(session, token_hash(token))
        account = await repository.get_account(session, learner) if learner else None
        if learner is None or account is None or account.gone:
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


async def account_is_active(session: AsyncSession, learner: uuid.UUID) -> bool:
    """False once the learner deleted the account, during the grace period too (D9).

    For background work that must not run for a disabled account, such as building a
    data export asked for just before the deletion (ADR 0029, ADR 0030).
    """
    account = await repository.get_account(session, learner)
    return account is not None and account.status == "active"


async def hold_active_account(session: AsyncSession, learner: uuid.UUID) -> bool:
    """Like `account_is_active`, and a deletion cannot start before the caller commits.

    For the transaction that stores a result which must not outlive a deletion, such
    as a finished data export (ADR 0029, ADR 0030).
    """
    return await repository.hold_active_account(session, learner)


async def get_profile(session: AsyncSession, learner: uuid.UUID) -> dict[str, object]:
    profile = await repository.get_profile(session, learner)
    if profile is None:
        raise ProblemError(401, "not_signed_in", "Sign in to continue.")
    return {**profile, "deletion_grace_days": get_settings().account_deletion_grace_days}


AccountsDep = Annotated[Accounts, Depends(get_accounts)]


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    """The learner's identity rows for their data export (#92, NFR-SEC-5).

    Password and token hashes are secrets of the service, not the learner's data, and
    are left out; everything else about the account and its sign-ins is included.
    """
    return ExportPart(
        tables=(
            await learner_rows(
                session, "identity.users", learner, column="id", omit=("password_hash",)
            ),
            await learner_rows(
                session,
                "identity.auth_sessions",
                learner,
                omit=("token_hash",),
                order_by="created_at",
            ),
            await learner_rows(
                session,
                "identity.one_time_tokens",
                learner,
                omit=("token_hash",),
                order_by="created_at",
            ),
            # Earlier deletions the learner cancelled by restoring the account (#120).
            # The storage prefix is an internal key, like the media keys.
            await learner_rows(
                session,
                "ops.deletion_requests",
                learner,
                column="subject_user_id",
                omit=("storage_prefixes",),
                order_by="requested_at",
            ),
        )
    )
