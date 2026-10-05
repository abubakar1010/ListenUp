"""The session state machine: plan paths, step gating, the entry lock, skips and completion.

This is the one place where step order lives (NFR-MNT-2). Every mode asks it for
permission through `practice.service.require_step` and reports through
`complete_step`; the database triggers `session_steps_order` and `sessions_entry_lock`
repeat the two rules that can be checked from stored data alone (Database Design 8).

Rules (SRS 4.4 and 6):
- FR-PL-1, FR-PL-2, SR-1: the entry choice (Blind, Dictation or both) picks the path,
  4 or 5 steps; Transcript, Card and Shadow always follow.
- FR-PL-4, SR-2: a step opens only when the step before it is done or skipped. Exactly
  one step is open while the session is active.
- FR-PL-5, SR-3: the entry choice can change until Transcript opens; then it is locked.
  A change rebuilds the steps that are not finished; a finished entry step stays.
- FR-PL-7, SR-4: Transcript and the entry steps cannot be skipped; Card and Shadow can,
  only with an explicit confirmation.
- SR-6, D12: the session is completed when Shadow is done or skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class Step(StrEnum):
    BLIND = "blind"
    DICTATION = "dictation"
    TRANSCRIPT = "transcript"
    CARD = "card"
    SHADOW = "shadow"


class Entry(StrEnum):
    BLIND = "blind"
    DICTATION = "dictation"
    BOTH = "both"


class StepStatus(StrEnum):
    LOCKED = "locked"
    OPEN = "open"
    DONE = "done"
    SKIPPED = "skipped"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


# `sessions.current_step` once the session is complete.
CURRENT_STEP_DONE = "done"

ENTRY_STEPS: dict[Entry, tuple[Step, ...]] = {
    Entry.BLIND: (Step.BLIND,),
    Entry.DICTATION: (Step.DICTATION,),
    Entry.BOTH: (Step.BLIND, Step.DICTATION),
}
FOLLOWING_STEPS = (Step.TRANSCRIPT, Step.CARD, Step.SHADOW)
SKIPPABLE_STEPS = frozenset({Step.CARD, Step.SHADOW})
FINISHED = frozenset({StepStatus.DONE, StepStatus.SKIPPED})


def path_for(entry: Entry) -> tuple[Step, ...]:
    """The ordered steps of a plan (FR-PL-2): 4 steps for one entry exercise, 5 for both."""
    return ENTRY_STEPS[entry] + FOLLOWING_STEPS


class PlanError(Exception):
    """A refused transition. Each subclass has a stable code the API returns."""

    code = "plan_error"


class StepLocked(PlanError):
    """The step asked for is not the open one (FR-PL-4)."""

    code = "step_locked"

    def __init__(self, step: Step, open_step: Step | None) -> None:
        super().__init__(f"{step} is not open; the open step is {open_step}")
        self.step = step
        self.open_step = open_step


class StepNotInPlan(PlanError):
    """The step is not on this session's path, for example Blind on a Dictation plan."""

    code = "step_not_in_plan"

    def __init__(self, step: Step) -> None:
        super().__init__(f"{step} is not part of this plan")
        self.step = step


class EntryLocked(PlanError):
    """The entry choice can no longer change (FR-PL-5)."""

    code = "entry_locked"


class StepNotSkippable(PlanError):
    """Only Card and Shadow can be skipped (FR-PL-7)."""

    code = "step_not_skippable"

    def __init__(self, step: Step) -> None:
        super().__init__(f"{step} cannot be skipped")
        self.step = step


class ConfirmationRequired(PlanError):
    """Skipping Card or Shadow needs the learner's explicit confirmation (FR-PL-7)."""

    code = "confirmation_required"

    def __init__(self, step: Step) -> None:
        super().__init__(f"skipping {step} needs confirmation")
        self.step = step


class SessionClosed(PlanError):
    """The session is completed or abandoned, so no step can change."""

    code = "session_closed"

    def __init__(self, status: SessionStatus) -> None:
        super().__init__(f"the session is {status}")
        self.status = status


@dataclass(frozen=True)
class StepState:
    step: Step
    position: int  # 1-based, as in practice.session_steps
    status: StepStatus


@dataclass(frozen=True)
class Plan:
    """One session's plan. Transitions return a new Plan and never change this one."""

    entry: Entry
    steps: tuple[StepState, ...]
    status: SessionStatus = SessionStatus.ACTIVE

    @classmethod
    def start(cls, entry: Entry) -> Plan:
        """A new plan with its first step open and every other step locked."""
        steps = tuple(
            StepState(step, position, StepStatus.OPEN if position == 1 else StepStatus.LOCKED)
            for position, step in enumerate(path_for(entry), start=1)
        )
        return cls(entry, steps)

    # Queries

    @property
    def open_step(self) -> Step | None:
        for state in self.steps:
            if state.status is StepStatus.OPEN:
                return state.step
        return None

    @property
    def current_step(self) -> str:
        """The value of `sessions.current_step`: the open step, or 'done' once complete."""
        open_step = self.open_step
        if open_step is not None:
            return open_step.value
        if self.is_complete:
            return CURRENT_STEP_DONE
        # A closed session that never completed keeps pointing at where it stopped.
        unfinished = [s for s in self.steps if s.status not in FINISHED]
        return unfinished[0].step.value if unfinished else CURRENT_STEP_DONE

    @property
    def is_complete(self) -> bool:
        """SR-6, D12: Shadow done or skipped, whatever happened to Card."""
        return self.state(Step.SHADOW).status in FINISHED

    @property
    def entry_locked(self) -> bool:
        """FR-PL-5: locked once Transcript has opened."""
        return self.state(Step.TRANSCRIPT).status is not StepStatus.LOCKED

    def has(self, step: Step) -> bool:
        return any(state.step is step for state in self.steps)

    def state(self, step: Step) -> StepState:
        for state in self.steps:
            if state.step is step:
                return state
        raise StepNotInPlan(step)

    def reached(self, step: Step) -> bool:
        """The step is open or finished: the session has got that far (FR-TX-5)."""
        return self.state(step).status is not StepStatus.LOCKED

    # Guards

    def require(self, step: Step) -> None:
        """Refuse unless `step` is the open step of an active session."""
        self._require_active()
        state = self.state(step)
        if state.status is not StepStatus.OPEN:
            raise StepLocked(step, self.open_step)

    def require_reached(self, step: Step) -> None:
        """Refuse unless the session has reached `step` (open, done or skipped)."""
        if not self.reached(step):
            raise StepLocked(step, self.open_step)

    # Transitions

    def complete(self, step: Step) -> Plan:
        """Finish the open step and open the next one (FR-PL-4); Shadow completes the plan."""
        self.require(step)
        return self._finish(step, StepStatus.DONE)

    def skip(self, step: Step, *, confirmed: bool) -> Plan:
        """Skip Card or Shadow after confirmation (FR-PL-7, SR-4)."""
        if step not in SKIPPABLE_STEPS:
            self.state(step)  # a step outside the path is reported as such first
            raise StepNotSkippable(step)
        self.require(step)
        if not confirmed:
            raise ConfirmationRequired(step)
        return self._finish(step, StepStatus.SKIPPED)

    def change_entry(self, entry: Entry) -> Plan:
        """Switch the entry choice while Transcript has not opened (FR-PL-5, SR-3).

        The new path is built afresh, except that entry steps already done keep their
        place and status: they must still be at the start of the new path, so a
        finished exercise cannot be removed. The first unfinished step opens.
        """
        self._require_active()
        if self.entry_locked:
            raise EntryLocked("the entry choice is locked once Transcript has opened")
        if entry is self.entry:
            return self
        finished = [s for s in self.steps if s.status in FINISHED]
        new_path = path_for(entry)
        if tuple(s.step for s in finished) != new_path[: len(finished)]:
            raise EntryLocked("a finished entry exercise cannot be removed from the plan")
        steps = list(finished)
        for position in range(len(finished) + 1, len(new_path) + 1):
            first_unfinished = position == len(finished) + 1
            status = StepStatus.OPEN if first_unfinished else StepStatus.LOCKED
            steps.append(StepState(new_path[position - 1], position, status))
        return replace(self, entry=entry, steps=tuple(steps))

    # Helpers

    def _require_active(self) -> None:
        if self.status is not SessionStatus.ACTIVE:
            raise SessionClosed(self.status)

    def _finish(self, step: Step, status: StepStatus) -> Plan:
        steps = list(self.steps)
        index = next(i for i, s in enumerate(steps) if s.step is step)
        steps[index] = replace(steps[index], status=status)
        if index + 1 < len(steps):
            steps[index + 1] = replace(steps[index + 1], status=StepStatus.OPEN)
        plan = replace(self, steps=tuple(steps))
        if plan.is_complete:
            plan = replace(plan, status=SessionStatus.COMPLETED)
        return plan


@dataclass(frozen=True)
class Passage:
    """The practised part of the clip in milliseconds, half-open [start, end) (C2)."""

    start_ms: int
    end_ms: int

    MIN_MS = 30_000
    MAX_MS = 900_000

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("a passage cannot start before the clip")
        if not self.MIN_MS <= self.end_ms - self.start_ms <= self.MAX_MS:
            raise ValueError("a passage is 30 seconds to 15 minutes long")

    @property
    def length_ms(self) -> int:
        return self.end_ms - self.start_ms
