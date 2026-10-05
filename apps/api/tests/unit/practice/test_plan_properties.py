"""Invariants of the session state machine under any sequence of actions (NFR-MNT-2)."""

from hypothesis import given
from hypothesis import strategies as st

from listenup.modules.practice.domain import (
    Entry,
    Plan,
    PlanError,
    SessionStatus,
    Step,
    StepStatus,
    path_for,
)

FINISHED = {StepStatus.DONE, StepStatus.SKIPPED}

actions = st.lists(
    st.one_of(
        st.tuples(st.just("complete"), st.sampled_from(Step)),
        st.tuples(st.just("skip"), st.sampled_from(Step), st.booleans()),
        st.tuples(st.just("entry"), st.sampled_from(Entry)),
    ),
    max_size=30,
)


def apply(plan: Plan, action: tuple[object, ...]) -> Plan:
    kind = action[0]
    if kind == "complete":
        return plan.complete(action[1])  # type: ignore[arg-type]
    if kind == "skip":
        return plan.skip(action[1], confirmed=action[2])  # type: ignore[arg-type]
    return plan.change_entry(action[1])  # type: ignore[arg-type]


def check(plan: Plan) -> None:
    states = plan.steps
    assert tuple(s.step for s in states) == path_for(plan.entry)
    assert [s.position for s in states] == list(range(1, len(states) + 1))
    # Finished steps form a prefix; then at most one open step; the rest are locked.
    kinds = ["finished" if s.status in FINISHED else s.status.value for s in states]
    finished = kinds.count("finished")
    assert kinds[:finished] == ["finished"] * finished
    rest = kinds[finished:]
    assert rest in ([], ["open"] + ["locked"] * (len(rest) - 1))
    # Only Card and Shadow are ever skipped.
    assert all(s.step in (Step.CARD, Step.SHADOW) for s in states if s.status is StepStatus.SKIPPED)
    # Completion is decided by Shadow alone (SR-6, D12).
    assert plan.is_complete == (plan.status is SessionStatus.COMPLETED) == (rest == [])
    # The entry is locked exactly when Transcript is no longer locked (FR-PL-5).
    assert plan.entry_locked == (plan.state(Step.TRANSCRIPT).status is not StepStatus.LOCKED)


@given(st.sampled_from(Entry), actions)
def test_any_sequence_of_actions_keeps_the_plan_valid(
    entry: Entry, steps: list[tuple[object, ...]]
) -> None:
    plan = Plan.start(entry)
    check(plan)
    for action in steps:
        before = plan
        try:
            plan = apply(plan, action)
        except PlanError:
            assert plan == before
            continue
        check(plan)
        if before.entry_locked:
            assert plan.entry is before.entry
