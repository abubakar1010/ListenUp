"""The Blind step: one unbroken listen, then a three-sentence gist (FR-BL-1 to FR-BL-5).

The public face of the blind module (Architecture 4.3). A try at the step is a
practice attempt (`practice.service.start_attempt`); this module adds its own row in
`practice.blind_attempts` with the server's record of the listen, and never writes
the attempts or step tables itself.

1. `start` opens an attempt on the open Blind step and returns a media URL bound to
   it: a random token whose hash is stored, valid until the passage's length plus a
   grace period (#62).
2. The player sends a heartbeat every 5 s; `heartbeat` judges it with the pure rules
   in `domain/listen.py` and continues, grants the one resume, or voids (#63).
3. The browser reports leaving, a reload or a seek it noticed with `void`.
4. `submit_gist` takes the gist once the whole passage has played by the server's
   clock, submits the attempt and completes the step (#65).

Every write locks the attempt's blind row first, so beats, voids and the gist of one
attempt run one after another. `now` is the server's clock, passed in by the route.
"""

import hashlib
import hmac
import logging
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import service as analytics
from listenup.modules.blind import repository
from listenup.modules.blind.domain import (
    MAX_CHARS,
    MIN_SENTENCES,
    Action,
    Beat,
    Listen,
    VoidReason,
    client_void,
    count_sentences,
    heard_whole_passage,
    judge,
)
from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.practice.service import Attempt, AttemptStatus, Step, StepStatus
from listenup.platform.errors import ProblemError
from listenup.platform.events import EventType, publish
from listenup.platform.export import ExportPart, learner_rows
from listenup.platform.storage import Storage

logger = logging.getLogger(__name__)

GRADE_GIST_JOB = "grading.grade_gist"
"""The job that will grade a submitted gist (FR-BL-6). It does not exist yet: grading
waits for the AI gateway (#64, ADR 0009) and #68, so `submit_gist` does not queue it."""


@dataclass(frozen=True)
class BlindAttempt:
    """One try at the Blind step as the learner sees it."""

    id: uuid.UUID
    session_id: uuid.UUID
    status: AttemptStatus
    void_reason: VoidReason | None
    started_at: datetime
    finished_at: datetime | None
    passage_start_ms: int
    passage_end_ms: int
    position_ms: int
    resume_count: int
    resume_stop_ms: int | None
    listen_complete: bool
    gist_text: str | None


@dataclass(frozen=True)
class BlindStep:
    session_id: uuid.UUID
    passage_start_ms: int
    passage_end_ms: int
    step_status: StepStatus
    attempt: BlindAttempt | None


@dataclass(frozen=True)
class Started:
    attempt: BlindAttempt
    media_token: str


@dataclass(frozen=True)
class Heartbeat:
    action: Action
    attempt: BlindAttempt
    resume_from_ms: int | None


@dataclass(frozen=True)
class GistSubmitted:
    attempt: BlindAttempt
    open_step: Step | None
    session_version: int


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _view(attempt: Attempt, row: repository.BlindRow) -> BlindAttempt:
    listen = row.listen
    return BlindAttempt(
        id=attempt.id,
        session_id=attempt.session_id,
        status=attempt.status,
        void_reason=VoidReason(row.void_reason) if row.void_reason else None,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        passage_start_ms=listen.passage_start_ms,
        passage_end_ms=listen.passage_end_ms,
        position_ms=listen.last_position_ms,
        resume_count=listen.resume_count,
        resume_stop_ms=listen.resume_stop_ms,
        listen_complete=listen.complete,
        gist_text=row.gist_text,
    )


def _not_found() -> ProblemError:
    return ProblemError(404, "attempt_not_found", "This attempt was not found.")


async def _load(
    db: AsyncSession, attempt_id: uuid.UUID, *, lock: bool = False
) -> tuple[Attempt, repository.BlindRow]:
    """The learner's Blind attempt with its row; 404 `attempt_not_found` otherwise."""
    row = await repository.get(db, attempt_id, lock=lock)
    if row is None:
        raise _not_found()
    attempt = await practice.get_attempt(db, attempt_id)
    if attempt.mode is not Step.BLIND:
        raise _not_found()  # pragma: no cover - a blind row always hangs off a Blind attempt
    return attempt, row


async def get_step(db: AsyncSession, session_id: uuid.UUID) -> BlindStep:
    """The Blind step of a session with its newest attempt, live or ended.

    409 `step_locked` before the plan reaches Blind, `step_not_in_plan` without Blind.
    """
    session = await practice.require_reached(db, session_id, Step.BLIND)
    state = next(s for s in session.steps if s.step is Step.BLIND)
    latest = await practice.latest_attempt(db, session_id, Step.BLIND)
    view = None
    if latest is not None:
        row = await repository.get(db, latest.id)
        view = _view(latest, row) if row else None
    return BlindStep(
        session.id, session.passage.start_ms, session.passage.end_ms, state.status, view
    )


async def start(db: AsyncSession, session_id: uuid.UUID, now: datetime) -> Started:
    """Start a listen on the open Blind step (FR-BL-1, #62).

    409 `step_locked` unless Blind is open; 409 `attempt_active` while another attempt
    is live (the page voids an unfinished one first, or shows the gist form).
    """
    session = await practice.require_step(db, session_id, Step.BLIND)
    attempt = await practice.start_attempt(db, session_id, Step.BLIND)
    token = secrets.token_urlsafe(32)
    listen = Listen.start(session.passage.start_ms, session.passage.end_ms, now)
    row = await repository.insert(db, attempt.id, attempt.user_id, _hash(token), listen)
    return Started(_view(attempt, row), token)


async def _void(
    db: AsyncSession,
    attempt: Attempt,
    listen: Listen,
    reason: VoidReason,
) -> BlindAttempt:
    row = await repository.save(db, attempt.id, listen, void_reason=reason.value)
    ended = await practice.finish_attempt(db, attempt.id, AttemptStatus.VOIDED)
    await publish(db, attempt.user_id, EventType.ATTEMPT_VOIDED, attempt.id)
    await analytics.record_blind_abandoned(
        db, attempt.user_id, attempt.session_id, attempt.id, reason=reason.value
    )
    # Only voids are logged (Database Design 11.1): beats are too many to keep.
    logger.info(
        "blind attempt voided",
        extra={
            "attempt": str(attempt.id),
            "reason": reason.value,
            "position_ms": listen.last_position_ms - listen.passage_start_ms,
            "resume_count": listen.resume_count,
        },
    )
    return _view(ended, row)


async def heartbeat(
    db: AsyncSession, attempt_id: uuid.UUID, beat: Beat, now: datetime
) -> Heartbeat:
    """Judge one beat (System Design 9.2): continue, resume once, or stop.

    A beat for an attempt that has already ended answers `stop` with the attempt, so
    a page that missed the void learns why.
    """
    attempt, row = await _load(db, attempt_id, lock=True)
    if attempt.status is not AttemptStatus.ACTIVE:
        return Heartbeat(Action.STOP, _view(attempt, row), None)
    verdict = judge(row.listen, beat, now)
    if verdict.void_reason is not None:
        view = await _void(db, attempt, verdict.listen, verdict.void_reason)
        return Heartbeat(Action.STOP, view, None)
    if verdict.listen != row.listen:
        row = await repository.save(db, attempt.id, verdict.listen)
    return Heartbeat(verdict.action, _view(attempt, row), verdict.resume_from_ms)


async def void(db: AsyncSession, attempt_id: uuid.UUID, reason: VoidReason) -> BlindAttempt:
    """The browser reports leaving the page, a reload or a seek (FR-BL-3, NFR-REL-3).

    Voids a listen in progress. Once the whole passage has played, or after the
    attempt ended, it changes nothing and answers the attempt as it is, so a repeated
    report is harmless.
    """
    attempt, row = await _load(db, attempt_id, lock=True)
    if attempt.status is not AttemptStatus.ACTIVE:
        return _view(attempt, row)
    effective = client_void(row.listen, reason)
    if effective is None:
        return _view(attempt, row)
    return await _void(db, attempt, row.listen, effective)


async def media_url(
    db: AsyncSession,
    storage: Storage,
    learner: uuid.UUID,
    attempt_id: uuid.UUID,
    token: str,
    now: datetime,
) -> str:
    """The signed URL of the passage's media, for this attempt only (#62).

    404 `attempt_not_found` for another learner's attempt, 404 `media_not_found` for a
    wrong token, 410 `media_expired` once the attempt has ended or its window is over.
    The storage URL lives only until the window ends.
    """
    row = await repository.get(db, attempt_id)
    if row is None:
        raise _not_found()
    if not token or not hmac.compare_digest(_hash(token), row.media_token_hash):
        raise ProblemError(404, "media_not_found", "This link does not belong to the attempt.")
    attempt = await practice.get_attempt(db, attempt_id)
    remaining = (row.media_expires_at - now).total_seconds()
    if attempt.status is not AttemptStatus.ACTIVE or remaining <= 0:
        raise ProblemError(
            410,
            "media_expired",
            "This listen has ended, so its audio is no longer available. Start again.",
        )
    session = await practice.get_session(db, attempt.session_id)
    item = await content.get_content(db, learner, session.content_id)
    return await content.media_url(
        db, storage, learner, item.media_object_id, ttl_seconds=math.ceil(remaining)
    )


async def submit_gist(
    db: AsyncSession, attempt_id: uuid.UUID, text: str, now: datetime
) -> GistSubmitted:
    """Store the gist, submit the attempt and complete the Blind step (FR-BL-4, #65).

    - 409 `attempt_closed`: the attempt was voided or already submitted.
    - 409 `listen_incomplete`: the passage has not played to the end, or not enough
      server time has passed to hear it.
    - 422 `gist_too_short` (with `sentences`) or `gist_too_long`.
    """
    attempt, row = await _load(db, attempt_id, lock=True)
    if attempt.status is not AttemptStatus.ACTIVE:
        raise ProblemError(409, "attempt_closed", "This attempt has already ended.")
    session = await practice.require_step(db, attempt.session_id, Step.BLIND)
    if not heard_whole_passage(row.listen, now):
        raise ProblemError(
            409,
            "listen_incomplete",
            "Listen to the whole passage before you write the gist.",
        )
    gist = text.strip()
    if len(gist) > MAX_CHARS:
        raise ProblemError(
            422,
            "gist_too_long",
            f"Keep the gist under {MAX_CHARS} characters. Keep the main points.",
        )
    sentences = count_sentences(gist)
    if sentences < MIN_SENTENCES:
        missing = MIN_SENTENCES - sentences
        more = "one more" if missing == 1 else f"{missing} more"
        raise ProblemError(
            422,
            "gist_too_short",
            f"{sentences} of {MIN_SENTENCES} sentences. Write {more}, then submit.",
            sentences=sentences,
        )
    row = await repository.save(db, attempt.id, row.listen, gist_text=gist)
    submitted = await practice.finish_attempt(db, attempt.id, AttemptStatus.SUBMITTED)
    advanced = await practice.complete_step(db, session, Step.BLIND)
    # TODO(#68): queue GRADE_GIST_JOB here, in this transaction, once the AI gateway
    # exists (`enqueue(db, GRADE_GIST_JOB, attempt_id=...)`). Grading never blocks the
    # plan, so the step is complete whatever happens to it.
    return GistSubmitted(_view(submitted, row), advanced.open_step, advanced.version)


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    """The learner's Blind attempts, gists included, for their data export (#92).

    The media token's hash only guarded the attempt's playback window; it is left out.
    """
    table = await learner_rows(
        session,
        "practice.blind_attempts",
        learner,
        omit=("media_token_hash",),
        order_by="attempt_id",
    )
    return ExportPart(tables=(table,))
