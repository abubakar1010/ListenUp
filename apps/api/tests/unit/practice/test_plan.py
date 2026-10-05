"""The session state machine (issue #47; SRS 4.4 and 6, SR-1 to SR-6; D12)."""

import pytest

from listenup.modules.practice.domain import (
    ConfirmationRequired,
    Entry,
    EntryLocked,
    Passage,
    Plan,
    SessionClosed,
    SessionStatus,
    Step,
    StepLocked,
    StepNotInPlan,
    StepNotSkippable,
    StepStatus,
    path_for,
)

B, D, T, C, S = Step.BLIND, Step.DICTATION, Step.TRANSCRIPT, Step.CARD, Step.SHADOW
PATHS = {
    Entry.BLIND: (B, T, C, S),
    Entry.DICTATION: (D, T, C, S),
    Entry.BOTH: (B, D, T, C, S),
}
ALL_ENTRIES = list(Entry)


def statuses(plan: Plan) -> dict[Step, str]:
    return {state.step: state.status.value for state in plan.steps}


def run(entry: Entry, *steps: Step) -> Plan:
    plan = Plan.start(entry)
    for step in steps:
        plan = plan.complete(step)
    return plan


def finish_entry(entry: Entry) -> Plan:
    return run(entry, *path_for(entry)[:-3])


# FR-PL-1, FR-PL-2, SR-1: the entry choice picks a 4 or 5 step path.


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_each_entry_builds_its_path(entry: Entry) -> None:
    plan = Plan.start(entry)

    assert tuple(s.step for s in plan.steps) == PATHS[entry]
    assert [s.position for s in plan.steps] == list(range(1, len(PATHS[entry]) + 1))
    assert len(plan.steps) == (5 if entry is Entry.BOTH else 4)


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_a_new_plan_opens_only_its_first_step(entry: Entry) -> None:
    plan = Plan.start(entry)

    assert plan.open_step is PATHS[entry][0]
    assert plan.current_step == PATHS[entry][0].value
    assert [s.status for s in plan.steps[1:]] == [StepStatus.LOCKED] * (len(plan.steps) - 1)
    assert plan.status is SessionStatus.ACTIVE


@pytest.mark.parametrize(("entry", "missing"), [(Entry.BLIND, D), (Entry.DICTATION, B)])
def test_the_entry_not_chosen_is_not_in_the_plan(entry: Entry, missing: Step) -> None:
    plan = Plan.start(entry)

    assert not plan.has(missing)
    with pytest.raises(StepNotInPlan):
        plan.require(missing)
    with pytest.raises(StepNotInPlan):
        plan.complete(missing)


# FR-PL-4, SR-2: a step opens only when the one before it is finished.


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_steps_open_one_after_another(entry: Entry) -> None:
    plan = Plan.start(entry)
    path = PATHS[entry]

    for index, step in enumerate(path):
        assert plan.open_step is step
        plan.require(step)
        for later in path[index + 1 :]:
            with pytest.raises(StepLocked) as refused:
                plan.require(later)
            assert refused.value.open_step is step
        plan = plan.complete(step)
        assert plan.state(step).status is StepStatus.DONE

    assert plan.open_step is None
    assert plan.status is SessionStatus.COMPLETED


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_a_locked_step_cannot_be_completed(entry: Entry) -> None:
    plan = Plan.start(entry)

    for step in PATHS[entry][1:]:
        with pytest.raises(StepLocked):
            plan.complete(step)


def test_a_finished_step_cannot_be_completed_again() -> None:
    plan = run(Entry.DICTATION, D)

    with pytest.raises(StepLocked) as refused:
        plan.complete(D)
    assert refused.value.open_step is T


def test_transcript_is_refused_while_dictation_is_open_naming_dictation() -> None:
    plan = run(Entry.BOTH, B)

    with pytest.raises(StepLocked) as refused:
        plan.require(T)

    assert (refused.value.step, refused.value.open_step) == (T, D)
    assert refused.value.code == "step_locked"


def test_reached_covers_open_and_finished_steps_only() -> None:
    plan = run(Entry.BOTH, B, D)

    for step in (B, D, T):
        plan.require_reached(step)
    for step in (C, S):
        with pytest.raises(StepLocked):
            plan.require_reached(step)


# FR-PL-5, SR-3: the entry choice changes until Transcript opens.


@pytest.mark.parametrize("old", ALL_ENTRIES)
@pytest.mark.parametrize("new", ALL_ENTRIES)
def test_the_entry_can_change_before_anything_is_finished(old: Entry, new: Entry) -> None:
    plan = Plan.start(old).change_entry(new)

    assert plan.entry is new
    assert plan == Plan.start(new)


def test_adding_dictation_while_blind_is_open_puts_it_after_blind() -> None:
    plan = Plan.start(Entry.BLIND).change_entry(Entry.BOTH)
    plan = plan.complete(B)

    assert plan.open_step is D
    assert not plan.entry_locked


def test_dropping_dictation_after_blind_opens_transcript_and_locks_the_entry() -> None:
    plan = run(Entry.BOTH, B)

    plan = plan.change_entry(Entry.BLIND)

    assert statuses(plan) == {B: "done", T: "open", C: "locked", S: "locked"}
    assert [s.position for s in plan.steps] == [1, 2, 3, 4]
    assert plan.entry_locked


def test_a_finished_entry_exercise_cannot_be_removed() -> None:
    plan = run(Entry.BOTH, B)

    with pytest.raises(EntryLocked):
        plan.change_entry(Entry.DICTATION)


def test_choosing_the_same_entry_changes_nothing() -> None:
    plan = run(Entry.BOTH, B)

    assert plan.change_entry(Entry.BOTH) is plan


@pytest.mark.parametrize("entry", ALL_ENTRIES)
def test_the_entry_locks_when_transcript_opens(entry: Entry) -> None:
    before = run(entry, *PATHS[entry][: len(PATHS[entry]) - 4])  # the last entry step open
    assert not before.entry_locked

    plan = finish_entry(entry)

    assert plan.open_step is T
    assert plan.entry_locked
    for other in ALL_ENTRIES:
        with pytest.raises(EntryLocked):
            plan.change_entry(other)


def test_the_entry_stays_locked_after_transcript() -> None:
    plan = run(Entry.DICTATION, D, T, C)

    with pytest.raises(EntryLocked):
        plan.change_entry(Entry.BOTH)


# FR-PL-7, SR-4: only Card and Shadow can be skipped, after confirmation.


@pytest.mark.parametrize("step", [B, D, T])
def test_entry_steps_and_transcript_cannot_be_skipped(step: Step) -> None:
    plan = Plan.start(Entry.BOTH)
    for earlier in PATHS[Entry.BOTH]:
        if earlier is step:
            break
        plan = plan.complete(earlier)

    with pytest.raises(StepNotSkippable):
        plan.skip(step, confirmed=True)


def test_skipping_a_step_outside_the_plan_says_so() -> None:
    with pytest.raises(StepNotInPlan):
        Plan.start(Entry.DICTATION).skip(B, confirmed=True)


@pytest.mark.parametrize("step", [C, S])
def test_skipping_needs_confirmation(step: Step) -> None:
    plan = run(Entry.DICTATION, D, T)
    if step is S:
        plan = plan.complete(C)

    with pytest.raises(ConfirmationRequired):
        plan.skip(step, confirmed=False)


def test_a_locked_card_cannot_be_skipped() -> None:
    plan = run(Entry.DICTATION, D)

    with pytest.raises(StepLocked) as refused:
        plan.skip(C, confirmed=True)
    assert refused.value.open_step is T


def test_shadow_cannot_be_skipped_before_card_is_finished() -> None:
    plan = run(Entry.BLIND, B, T)

    with pytest.raises(StepLocked):
        plan.skip(S, confirmed=True)


def test_skipping_card_opens_shadow() -> None:
    plan = run(Entry.BLIND, B, T).skip(C, confirmed=True)

    assert statuses(plan) == {B: "done", T: "done", C: "skipped", S: "open"}
    assert plan.status is SessionStatus.ACTIVE


# SR-6, D12: complete when Shadow is done or skipped, whatever happened to Card.


@pytest.mark.parametrize("entry", ALL_ENTRIES)
@pytest.mark.parametrize("card", ["done", "skipped"])
@pytest.mark.parametrize("shadow", ["done", "skipped"])
def test_the_session_completes_when_shadow_is_finished(
    entry: Entry, card: str, shadow: str
) -> None:
    plan = finish_entry(entry).complete(T)
    plan = plan.complete(C) if card == "done" else plan.skip(C, confirmed=True)
    assert not plan.is_complete
    assert plan.open_step is S

    plan = plan.complete(S) if shadow == "done" else plan.skip(S, confirmed=True)

    assert plan.is_complete
    assert plan.status is SessionStatus.COMPLETED
    assert plan.current_step == "done"
    assert plan.open_step is None


def test_an_open_shadow_is_not_complete() -> None:
    plan = run(Entry.DICTATION, D, T, C)

    assert plan.open_step is S
    assert not plan.is_complete
    assert plan.status is SessionStatus.ACTIVE


def test_a_completed_session_refuses_every_change() -> None:
    plan = run(Entry.DICTATION, D, T, C, S)

    with pytest.raises(SessionClosed):
        plan.require(S)
    with pytest.raises(SessionClosed):
        plan.complete(S)
    with pytest.raises(SessionClosed):
        plan.skip(S, confirmed=True)
    with pytest.raises(SessionClosed):
        plan.change_entry(Entry.BLIND)
    plan.require_reached(T)  # reading what was reached still works


def test_an_abandoned_session_refuses_every_change() -> None:
    plan = Plan(Entry.BLIND, Plan.start(Entry.BLIND).steps, SessionStatus.ABANDONED)

    with pytest.raises(SessionClosed):
        plan.require(B)
    with pytest.raises(SessionClosed):
        plan.change_entry(Entry.BOTH)
    assert plan.current_step == "blind"


# SR-5: voiding a Blind attempt belongs to the Blind mode; the plan only sees completion.


def test_blind_stays_open_until_the_mode_reports_it_complete() -> None:
    plan = Plan.start(Entry.BLIND)

    plan.require(B)  # a voided attempt and its restart both start from here
    plan.require(B)

    assert plan.open_step is B


def test_transitions_never_change_the_plan_they_start_from() -> None:
    plan = Plan.start(Entry.BOTH)

    plan.complete(B)

    assert plan == Plan.start(Entry.BOTH)


# C2: a passage is 30 seconds to 15 minutes.


@pytest.mark.parametrize(("start", "end"), [(0, 30_000), (5_000, 905_000)])
def test_passage_bounds_are_inclusive(start: int, end: int) -> None:
    assert Passage(start, end).length_ms == end - start


@pytest.mark.parametrize(("start", "end"), [(0, 29_999), (0, 900_001), (-1, 40_000)])
def test_passages_outside_the_bounds_are_refused(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        Passage(start, end)
