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

from sqlalchemy.ext.asyncio import AsyncSession

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
from listenup.platform.errors import ProblemError
from listenup.platform.ids import uuid7

__all__ = [
    "Entry",
    "Passage",
    "PracticeSession",
    "SessionStatus",
    "Step",
    "StepState",
    "StepStatus",
    "change_entry",
    "complete_step",
    "get_session",
    "require_reached",
    "require_step",
    "skip_step",
    "start_session",
]


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
    row, steps = found
    return PracticeSession(
        id=row.id,
        user_id=row.user_id,
        content_id=row.content_id,
        passage=row.passage,
        plan=_plan(row.entry, row.status, steps),
        version=row.version,
        entry_locked_at=row.entry_locked_at,
        completed_at=row.completed_at,
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
    db: AsyncSession, practice: PracticeSession, step: Step, *, confirmed: bool
) -> PracticeSession:
    """Skip Card or Shadow; `confirmed` must be true (FR-PL-7, SR-4)."""
    return await _transition(db, practice, lambda plan: plan.skip(step, confirmed=confirmed))


async def change_entry(
    db: AsyncSession, practice: PracticeSession, entry: Entry
) -> PracticeSession:
    """Change the entry choice until Transcript opens (FR-PL-5, SR-3)."""
    return await _transition(db, practice, lambda plan: plan.change_entry(entry))


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
    )


async def latest_session_status(
    db: AsyncSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SessionStatus]:
    """For each content item, the status of the learner's newest session on it (FR-LB-1).

    Items without a session are left out. Row-level security limits it to the learner.
    """
    found = await repository.latest_status_by_content(db, content_ids)
    return {content_id: SessionStatus(status) for content_id, status in found.items()}
