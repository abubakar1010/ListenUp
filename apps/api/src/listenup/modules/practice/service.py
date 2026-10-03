"""The practice module's public API: sessions and the gate every mode passes through.

Other modules use only this file (Architecture 4.3). A mode endpoint first calls
`require_step(db, session_id, Step.X)`, which refuses with 409 `step_locked` naming the
open step unless X is open, then does its work and reports with
`complete_step(db, session, Step.X)` in the same transaction (FR-PL-4). Transcript
data is gated with `require_reached`, which also accepts a finished step (FR-TX-5).

The rules themselves live in `domain/plan.py`; this file loads a session, asks the
plan, and writes the result with an optimistic check on `sessions.version`: if
another request changed the session in between, the write is refused with 409
`session_changed` and the caller reloads.

`db` is the request's `DbSession`, already scoped to the learner by `CurrentLearner`.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.practice import repository
from listenup.modules.practice.domain import (
    ConfirmationRequired,
    Entry,
    EntryLocked,
    Passage,
    Plan,
    PlanError,
    SessionClosed,
    SessionStatus,
    Step,
    StepLocked,
    StepNotInPlan,
    StepNotSkippable,
    StepState,
    StepStatus,
)
from listenup.modules.practice.domain import cursor as cursors
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7

__all__ = [
    "Attempt",
    "AttemptStatus",
    "Entry",
    "Passage",
    "PracticeSession",
    "SessionPage",
    "SessionStatus",
    "Step",
    "StepState",
    "StepStatus",
    "active_attempt",
    "change_entry",
    "complete_step",
    "finish_attempt",
    "get_attempt",
    "get_session",
    "latest_attempt",
    "list_sessions",
    "require_reached",
    "require_step",
    "skip_step",
    "start_attempt",
    "start_plan",
    "start_session",
]

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class PracticeSession:
    """A snapshot of one session. `version` is what the next write expects to find."""

    id: uuid.UUID
    user_id: uuid.UUID
    content_id: uuid.UUID
    passage: Passage
    plan: Plan
    version: int
    entry_locked_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def entry(self) -> Entry:
        return self.plan.entry

    @property
    def status(self) -> SessionStatus:
        return self.plan.status

    @property
    def open_step(self) -> Step | None:
        return self.plan.open_step

    @property
    def current_step(self) -> str:
        return self.plan.current_step

    @property
    def steps(self) -> tuple[StepState, ...]:
        return self.plan.steps

    @property
    def entry_locked(self) -> bool:
        return self.plan.entry_locked

    @property
    def open_position(self) -> int | None:
        """The open step's place in the plan, the N of "Step N of M"; None when closed."""
        for state in self.plan.steps:
            if state.status is StepStatus.OPEN:
                return state.position
        return None


def problem_for(error: PlanError) -> ProblemError:
    """The problem-details response for a refused transition."""
    if isinstance(error, StepLocked):
        open_step = error.open_step.value if error.open_step else None
        where = f"Finish {open_step} first." if open_step else "No step is open."
        return ProblemError(
            409,
            "step_locked",
            f"The {error.step} step is locked. {where}",
            step=error.step.value,
            open_step=open_step,
        )
    if isinstance(error, StepNotInPlan):
        return ProblemError(
            409,
            "step_not_in_plan",
            f"This plan has no {error.step} step.",
            step=error.step.value,
        )
    if isinstance(error, EntryLocked):
        return ProblemError(409, "entry_locked", f"The entry choice cannot change: {error}.")
    if isinstance(error, StepNotSkippable):
        return ProblemError(
            409,
            "step_not_skippable",
            "Only Card and Shadow can be skipped.",
            step=error.step.value,
        )
    if isinstance(error, ConfirmationRequired):
        return ProblemError(
            422,
            "confirmation_required",
            f"Confirm that you want to skip {error.step}.",
            step=error.step.value,
        )
    if isinstance(error, SessionClosed):
        return ProblemError(409, "session_closed", f"This session is {error.status}.")
    raise error  # pragma: no cover - every PlanError subclass is mapped above


def _not_found() -> ProblemError:
    return ProblemError(404, "session_not_found", "There is no such session.")


def _changed() -> ProblemError:
    return ProblemError(
        409, "session_changed", "The session changed in another request. Reload and try again."
    )


def _plan(entry: str, status: str, steps: list[repository.StepRow]) -> Plan:
    return Plan(
        Entry(entry),
        tuple(StepState(Step(s.step), s.position, StepStatus(s.status)) for s in steps),
        SessionStatus(status),
    )


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> PracticeSession:
    """The learner's session, or 404 `session_not_found` (also for another learner's)."""
    found = await repository.find_session(db, session_id)
    if found is None:
        raise _not_found()
    return _snapshot(*found)


def _snapshot(row: repository.SessionRow, steps: list[repository.StepRow]) -> PracticeSession:
    return PracticeSession(
        id=row.id,
        user_id=row.user_id,
        content_id=row.content_id,
        passage=row.passage,
        plan=_plan(row.entry, row.status, steps),
        version=row.version,
        entry_locked_at=row.entry_locked_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def start_session(
    db: AsyncSession,
    learner: uuid.UUID,
    content_id: uuid.UUID,
    passage: Passage,
    entry: Entry,
) -> PracticeSession:
    """Create a session on one of the learner's content items with its first step open.

    404 `content_not_found` when the learner has no such content item. Whether the
    content is ready and the passage fits the clip is the caller's check (#48).
    """
    plan = Plan.start(entry)
    session_id = uuid7()
    created = await repository.insert_session(
        db,
        session_id=session_id,
        user_id=learner,
        content_id=content_id,
        passage=passage,
        entry=entry.value,
        current_step=plan.current_step,
    )
    if not created:
        raise ProblemError(404, "content_not_found", "There is no such content item.")
    await repository.insert_steps(db, session_id, learner, list(plan.steps))
    return await get_session(db, session_id)


async def require_step(db: AsyncSession, session_id: uuid.UUID, step: Step) -> PracticeSession:
    """The session, if `step` is its open step; else 409 `step_locked` naming the open step."""
    practice = await get_session(db, session_id)
    try:
        practice.plan.require(step)
    except PlanError as error:
        raise problem_for(error) from error
    return practice


async def require_reached(db: AsyncSession, session_id: uuid.UUID, step: Step) -> PracticeSession:
    """The session, if it has reached `step` (open, done or skipped); else 409 `step_locked`."""
    practice = await get_session(db, session_id)
    try:
        practice.plan.require_reached(step)
    except PlanError as error:
        raise problem_for(error) from error
    return practice


async def complete_step(db: AsyncSession, practice: PracticeSession, step: Step) -> PracticeSession:
    """Finish `step` and open the next one; finishing Shadow completes the session (SR-6)."""
    return await _transition(db, practice, lambda plan: plan.complete(step))


async def skip_step(
    db: AsyncSession,
    practice: PracticeSession,
    step: Step,
    *,
    confirmed: bool,
    expected_version: int | None = None,
) -> PracticeSession:
    """Skip Card or Shadow; `confirmed` must be true (FR-PL-7, SR-4).

    With `expected_version` (the version the client last saw), a session that changed
    since is refused with 409 `session_changed` before any rule is checked.
    """
    _check_version(practice, expected_version)
    return await _transition(db, practice, lambda plan: plan.skip(step, confirmed=confirmed))


async def change_entry(
    db: AsyncSession,
    practice: PracticeSession,
    entry: Entry,
    *,
    expected_version: int | None = None,
) -> PracticeSession:
    """Change the entry choice until Transcript opens (FR-PL-5, SR-3).

    `expected_version` works as in `skip_step`.
    """
    _check_version(practice, expected_version)
    return await _transition(db, practice, lambda plan: plan.change_entry(entry))


def _check_version(practice: PracticeSession, expected_version: int | None) -> None:
    if expected_version is not None and expected_version != practice.version:
        raise _changed()


async def _transition(
    db: AsyncSession,
    practice: PracticeSession,
    change: Callable[[Plan], Plan],
) -> PracticeSession:
    try:
        new = change(practice.plan)
    except PlanError as error:
        raise problem_for(error) from error
    if new is practice.plan:
        return practice
    stamps = await repository.update_session(
        db,
        practice.id,
        practice.version,
        repository.SessionUpdate(
            entry=new.entry.value,
            current_step=new.current_step,
            status=new.status.value,
            lock_entry=new.entry_locked,
            completed=new.status is SessionStatus.COMPLETED,
        ),
    )
    if stamps is None:
        raise _changed()
    if new.entry is not practice.plan.entry:
        await repository.delete_unfinished_steps(db, practice.id)
        unfinished = [s for s in new.steps if s.status not in repository.FINISHED]
        await repository.insert_steps(db, practice.id, practice.user_id, unfinished)
    else:
        old = {s.step: s.status for s in practice.plan.steps}
        changed = [s for s in new.steps if old[s.step] is not s.status]
        await repository.update_steps(db, practice.id, changed)
    return PracticeSession(
        id=practice.id,
        user_id=practice.user_id,
        content_id=practice.content_id,
        passage=practice.passage,
        plan=new,
        version=stamps.version,
        entry_locked_at=stamps.entry_locked_at,
        completed_at=stamps.completed_at,
        created_at=practice.created_at,
        updated_at=stamps.updated_at,
    )


async def latest_session_status(
    db: AsyncSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SessionStatus]:
    """For each content item, the status of the learner's newest session on it (FR-LB-1).

    Items without a session are left out. Row-level security limits it to the learner.
    """
    found = await repository.latest_status_by_content(db, content_ids)
    return {content_id: SessionStatus(status) for content_id, status in found.items()}


_NOT_READY = {
    "pending": "This clip is still being prepared. You can start a plan as soon as it is ready.",
    "downloading": "This clip is still downloading. You can start a plan as soon as it is ready.",
    "failed": "This clip could not be processed, so it cannot be practised. Add the file again.",
    "expired": "This clip needs downloading again before you can practise it.",
}


async def start_plan(
    db: AsyncSession,
    learner: uuid.UUID,
    content_id: uuid.UUID,
    start_ms: int,
    end_ms: int,
    entry: Entry,
) -> PracticeSession:
    """Start a plan on one of the learner's clips (FR-PL-1, FR-PL-2, FR-LB-2).

    The checks `start_session` leaves to its caller:
    - 422 `invalid_passage`: the passage starts before the clip or is not 30 s to 15 min
      long (C2).
    - 404 `content_not_found`: no such content item for this learner.
    - 409 `content_not_ready`: the clip is not playable yet (or failed, or expired).
      Blind and Dictation need playback, so a plan never starts on a clip that cannot
      play; the problem carries the clip's `content_status`.
    - 422 `clip_too_short`: the clip is under 30 s, so no passage fits.
    - 422 `passage_outside_clip`: the passage ends after the clip; carries `duration_ms`.
    The duration checks apply once the clip's duration is known.
    """
    try:
        passage = Passage(start_ms, end_ms)
    except ValueError as error:
        raise ProblemError(
            422,
            "invalid_passage",
            f"Choose a part of the clip from 30 seconds to 15 minutes long ({error}).",
        ) from error
    item = await content.find_content(db, content_id)
    if item is None:
        raise ProblemError(404, "content_not_found", "There is no such content item.")
    if item.status != "playable":
        raise ProblemError(
            409,
            "content_not_ready",
            _NOT_READY.get(item.status, "This clip cannot be played yet."),
            content_status=item.status,
        )
    if item.duration_ms is not None:
        if item.duration_ms < Passage.MIN_MS:
            raise ProblemError(
                422,
                "clip_too_short",
                "This clip is shorter than 30 seconds, too short for a plan. Add a longer clip.",
                duration_ms=item.duration_ms,
            )
        if passage.end_ms > item.duration_ms:
            raise ProblemError(
                422,
                "passage_outside_clip",
                "The part you chose ends after the clip does. Choose an end time within the clip.",
                duration_ms=item.duration_ms,
            )
    return await start_session(db, learner, content_id, passage, entry)


@dataclass(frozen=True)
class SessionPage:
    items: list[PracticeSession]
    next_cursor: str | None


async def list_sessions(
    db: AsyncSession,
    learner: uuid.UUID,
    cursor: str | None = None,
    limit: int = PAGE_SIZE,
) -> SessionPage:
    """The learner's sessions, most recently changed first, in keyset pages.

    400 `invalid_cursor` for a cursor this API did not hand out.
    """
    after = None
    if cursor:
        try:
            decoded = cursors.decode(cursor)
        except cursors.InvalidCursor as error:
            raise ProblemError(
                400, "invalid_cursor", "This page link is not valid. Load the list again."
            ) from error
        after = (decoded.updated_at, decoded.id)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    rows = await repository.list_sessions(db, learner, limit + 1, after)
    items = [_snapshot(row, steps) for row, steps in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = cursors.encode(cursors.Cursor(last.updated_at, last.id))
    return SessionPage(items, next_cursor)


# --- Attempts: one learner's try at a Blind or Dictation step (migration 0008) ----------

ATTEMPT_MODES = (Step.BLIND, Step.DICTATION)


class AttemptStatus(StrEnum):
    ACTIVE = "active"
    SUBMITTED = "submitted"
    VOIDED = "voided"


@dataclass(frozen=True)
class Attempt:
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    mode: Step
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime | None


def _attempt(row: repository.AttemptRow) -> Attempt:
    return Attempt(
        row.id,
        row.session_id,
        row.user_id,
        Step(row.mode),
        AttemptStatus(row.status),
        row.started_at,
        row.finished_at,
    )


def _check_mode(mode: Step) -> None:
    if mode not in ATTEMPT_MODES:
        raise ValueError(f"attempts exist only for {ATTEMPT_MODES}, not {mode}")


async def start_attempt(db: AsyncSession, session_id: uuid.UUID, mode: Step) -> Attempt:
    """Start a try at an open Blind or Dictation step (FR-PL-4: one live try at a time).

    Refused with 409 `step_locked` unless that step is open, and with 409
    `attempt_active` (naming the live attempt) while another try is still active; the
    mode decides whether to resume it or void it first.
    """
    _check_mode(mode)
    practice = await require_step(db, session_id, mode)
    try:
        async with db.begin_nested():
            row = await repository.insert_attempt(
                db, uuid7(), practice.id, practice.user_id, mode.value
            )
    except IntegrityError as error:
        if "attempts_one_active" not in str(error.orig):
            raise
        live = await repository.active_attempt(db, practice.id, mode.value)
        raise ProblemError(
            409,
            "attempt_active",
            "This step already has an attempt in progress.",
            attempt_id=str(live.id) if live else None,
        ) from None
    return _attempt(row)


async def active_attempt(db: AsyncSession, session_id: uuid.UUID, mode: Step) -> Attempt | None:
    _check_mode(mode)
    row = await repository.active_attempt(db, session_id, mode.value)
    return _attempt(row) if row else None


async def latest_attempt(db: AsyncSession, session_id: uuid.UUID, mode: Step) -> Attempt | None:
    """The newest attempt at a step, live or ended; None before the first one.

    A mode uses it to tell the learner how the last try ended, for example after a reload.
    """
    _check_mode(mode)
    row = await repository.latest_attempt(db, session_id, mode.value)
    return _attempt(row) if row else None


async def get_attempt(db: AsyncSession, attempt_id: uuid.UUID) -> Attempt:
    """The learner's attempt; 404 `attempt_not_found` for anyone else's."""
    row = await repository.get_attempt(db, attempt_id)
    if row is None:
        raise ProblemError(404, "attempt_not_found", "This attempt was not found.")
    return _attempt(row)


async def finish_attempt(db: AsyncSession, attempt_id: uuid.UUID, status: AttemptStatus) -> Attempt:
    """Submit or void an active attempt; 409 `attempt_closed` if it already ended.

    Finishing an attempt does not complete the step: the mode calls `complete_step`
    when its own rules say the step is done.
    """
    if status is AttemptStatus.ACTIVE:
        raise ValueError("an attempt can only be finished as submitted or voided")
    row = await repository.finish_attempt(db, attempt_id, status.value)
    if row is None:
        await get_attempt(db, attempt_id)  # 404 when it is not the learner's
        raise ProblemError(409, "attempt_closed", "This attempt has already ended.")
    return _attempt(row)
