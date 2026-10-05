"""What each change of a plan records, and how marks are keyed (#101, ADR 0033)."""

import pytest

from listenup.modules.analytics.domain import (
    EventType,
    StepChange,
    mark_pattern,
    require_one_of,
    step_changes,
)

STARTED, COMPLETED = EventType.STEP_STARTED, EventType.STEP_COMPLETED


def test_a_new_plan_starts_its_open_step() -> None:
    plan = {"blind": "open", "transcript": "locked", "card": "locked", "shadow": "locked"}

    assert step_changes({}, plan) == [StepChange(STARTED, "blind")]


def test_finishing_a_step_completes_it_and_starts_the_next() -> None:
    before = {"blind": "open", "dictation": "locked", "transcript": "locked"}
    after = {"blind": "done", "dictation": "open", "transcript": "locked"}

    assert step_changes(before, after) == [
        StepChange(COMPLETED, "blind", "done"),
        StepChange(STARTED, "dictation"),
    ]


def test_a_skip_is_a_completion_with_its_outcome() -> None:
    before = {"transcript": "done", "card": "open", "shadow": "locked"}
    after = {"transcript": "done", "card": "skipped", "shadow": "open"}

    assert step_changes(before, after) == [
        StepChange(COMPLETED, "card", "skipped"),
        StepChange(STARTED, "shadow"),
    ]


def test_an_entry_change_starts_only_the_newly_open_step() -> None:
    # Blind only -> Dictation only: Blind leaves the plan, Dictation opens.
    before = {"blind": "open", "transcript": "locked", "card": "locked", "shadow": "locked"}
    after = {"dictation": "open", "transcript": "locked", "card": "locked", "shadow": "locked"}

    assert step_changes(before, after) == [StepChange(STARTED, "dictation")]


def test_nothing_changed_records_nothing() -> None:
    plan = {"blind": "done", "transcript": "open"}

    assert step_changes(plan, plan) == []


def test_an_unknown_step_is_refused() -> None:
    with pytest.raises(ValueError):
        step_changes({}, {"warmup": "open"})


def test_a_marked_phrase_is_kept_only_as_a_stable_hash() -> None:
    key = mark_pattern("Could've,")

    assert key == mark_pattern("could\u2019ve") == mark_pattern("  COULD'VE  ")
    assert key != mark_pattern("could have")
    assert "could" not in key
    assert len(key) == 32


def test_a_phrase_without_words_is_refused() -> None:
    with pytest.raises(ValueError):
        mark_pattern(" ... ")


def test_values_outside_the_allowed_set_are_refused() -> None:
    assert require_one_of("path", "both", ("blind", "dictation", "both")) == "both"
    with pytest.raises(ValueError):
        require_one_of("path", "all", ("blind", "dictation", "both"))
