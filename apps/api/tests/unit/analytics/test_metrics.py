"""The five PRD 2 success metrics, computed from hand-built events (#101, ADR 0033)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from listenup.modules.analytics.domain import Event, EventType, compute_report
from listenup.modules.analytics.domain.metrics import (
    first_listen,
    mark_reuse,
    plan_completion,
    repeat_failures,
    return_rate,
)

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)
AS_OF = datetime(2026, 12, 1, tzinfo=UTC)


def at(day: int, seconds: float = 0) -> datetime:
    """A moment in October 2026 (day 0 is 30 September, before the range)."""
    return START + timedelta(days=day - 1, seconds=seconds)


def plan(learner: uuid.UUID, when: datetime, session: uuid.UUID | None = None) -> Event:
    return Event(EventType.PLAN_STARTED, learner, session or uuid.uuid4(), when)


def step(kind: EventType, session: uuid.UUID, name: str, when: datetime) -> Event:
    return Event(kind, uuid.uuid4(), session, when, step=name, session_id=session)


def added(learner: uuid.UUID, content: uuid.UUID, when: datetime) -> Event:
    return Event(EventType.CONTENT_ADDED, learner, content, when, content_id=content)


def listen(learner: uuid.UUID, content: uuid.UUID, when: datetime) -> Event:
    return Event(EventType.LISTEN_STARTED, learner, uuid.uuid4(), when, content_id=content)


def mark(learner: uuid.UUID, session: uuid.UUID, pattern: str, when: datetime) -> Event:
    return Event(
        EventType.MARK_CREATED,
        learner,
        uuid.uuid4(),
        when,
        session_id=session,
        properties={"pattern": pattern},
    )


# Plan completion rate


def test_plan_completion_counts_plans_started_in_the_range() -> None:
    learner = uuid.uuid4()
    finished, at_shadow, stalled, earlier = (uuid.uuid4() for _ in range(4))
    events = [
        plan(learner, at(2), finished),
        plan(learner, at(3), at_shadow),
        plan(learner, at(4), stalled),
        plan(learner, at(0), earlier),  # before the range: not in the cohort
        step(EventType.STEP_STARTED, finished, "shadow", at(2, 600)),
        step(EventType.STEP_COMPLETED, finished, "shadow", at(40)),  # after END still counts
        step(EventType.STEP_STARTED, at_shadow, "shadow", at(3, 600)),
        step(EventType.STEP_STARTED, earlier, "shadow", at(2)),
        step(EventType.STEP_COMPLETED, earlier, "shadow", at(2)),
    ]

    result = plan_completion(events, START, END)

    assert (result.started, result.reached_final_step, result.completed) == (3, 2, 1)
    assert result.reach_rate == pytest.approx(2 / 3)
    assert result.completion_rate == pytest.approx(1 / 3)


def test_plan_completion_without_plans_has_no_rate() -> None:
    result = plan_completion([], START, END)

    assert result.started == 0
    assert result.completion_rate is None


# Time to first listen


def test_time_to_first_listen_takes_the_first_listen_on_each_clip() -> None:
    learner = uuid.uuid4()
    quick, slow, unheard = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [
        added(learner, quick, at(2)),
        listen(learner, quick, at(2, 45)),
        listen(learner, quick, at(2, 20)),  # the earlier listen wins
        added(learner, slow, at(3)),
        listen(learner, slow, at(3, 300)),
        added(learner, unheard, at(4)),
        added(learner, uuid.uuid4(), at(0)),  # before the range
    ]

    result = first_listen(events, START, END)

    assert result.clips_added == 3
    assert result.listened == 2
    assert result.median_seconds == pytest.approx(160)
    assert result.p90_seconds == pytest.approx(300)
    assert result.under_target == 1
    assert result.under_target_rate == pytest.approx(0.5)


def test_another_learners_listen_does_not_count() -> None:
    mine, theirs, content = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [added(mine, content, at(2)), listen(theirs, content, at(2, 10))]

    result = first_listen(events, START, END)

    assert (result.clips_added, result.listened, result.median_seconds) == (1, 0, None)


# Return rate


def test_return_rate_counts_3_plans_within_14_days_of_the_first() -> None:
    back, once, late, still_open, old = (uuid.uuid4() for _ in range(5))
    events = [
        plan(back, at(2)),
        plan(back, at(5)),
        plan(back, at(16, -1)),  # a second inside 14 days
        plan(once, at(3)),
        plan(late, at(4)),
        plan(late, at(10)),
        plan(late, at(18, 1)),  # day 14 plus a second: outside the window
        plan(still_open, at(30)),  # the window ends after AS_OF below
        plan(old, at(0)),  # first plan before the range: not new
        plan(old, at(2)),
        plan(old, at(3)),
    ]

    result = return_rate(events, START, END, as_of=at(35))

    assert (result.new_learners, result.returned, result.window_open) == (4, 1, 1)
    assert result.rate == pytest.approx(1 / 3)


def test_return_rate_reports_no_rate_while_every_window_is_open() -> None:
    result = return_rate([plan(uuid.uuid4(), at(30))], START, END, as_of=at(31))

    assert (result.new_learners, result.window_open, result.rate) == (1, 1, None)


# Mark reuse


def test_mark_reuse_has_no_data_until_cards_or_shadow_exist() -> None:
    session = uuid.uuid4()
    events = [step(EventType.STEP_STARTED, session, "transcript", at(2))]

    assert mark_reuse(events, START, END) is None


def test_mark_reuse_counts_cards_and_shadow_segments_per_session_at_transcript() -> None:
    learner = uuid.uuid4()
    a, b, outside = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def by(kind: EventType, session: uuid.UUID, **properties: object) -> Event:
        return Event(kind, learner, uuid.uuid4(), at(3), session_id=session, properties=properties)

    events = [
        step(EventType.STEP_STARTED, a, "transcript", at(2)),
        step(EventType.STEP_STARTED, b, "transcript", at(2)),
        step(EventType.STEP_STARTED, outside, "transcript", at(0)),
        by(EventType.CARD_CREATED, a),
        by(EventType.CARD_CREATED, a),
        by(EventType.SHADOW_ROUND_COMPLETED, a, round=1),
        by(EventType.SHADOW_ROUND_COMPLETED, a, round=2),  # one segment, however many rounds
        by(EventType.CARD_CREATED, outside),
    ]

    result = mark_reuse(events, START, END)

    assert result is not None
    assert (result.sessions_reached_transcript, result.cards, result.shadow_segments) == (2, 2, 1)
    assert result.rate == pytest.approx(1.5)


# Repeat-failure trend


def test_repeat_failures_have_no_data_until_marks_exist() -> None:
    assert repeat_failures([plan(uuid.uuid4(), at(2))], START, END) is None


def test_a_mark_repeats_when_an_earlier_session_marked_the_same_pattern() -> None:
    learner, other = uuid.uuid4(), uuid.uuid4()
    first, second, third, theirs = (uuid.uuid4() for _ in range(4))
    events = [
        plan(learner, at(0), first),
        plan(learner, at(5), second),
        plan(learner, at(9), third),
        plan(other, at(5), theirs),
        mark(learner, first, "gonna", at(0)),  # before the range: counts as earlier
        mark(learner, first, "could-have", at(0)),
        mark(learner, second, "gonna", at(5)),  # repeat
        mark(learner, second, "a-lot-of", at(5)),
        mark(learner, second, "a-lot-of", at(5, 10)),  # same session: not a repeat
        mark(learner, third, "a-lot-of", at(9)),  # repeat of session 2
        mark(other, theirs, "could-have", at(5)),  # another learner's history does not count
    ]

    result = repeat_failures(events, START, END)

    assert result is not None
    assert (result.marks, result.repeats) == (5, 2)
    by_number = {s.session_number: (s.marks, s.repeats) for s in result.by_session}
    assert by_number[1] == (1, 0)  # the other learner's first session
    assert by_number[2] == (3, 1)
    assert by_number[3] == (1, 1)
    assert len(result.by_session) == 8
    assert result.by_session[7].share is None


# The whole report


def test_the_report_ignores_events_after_as_of_and_checks_its_range() -> None:
    learner, session = uuid.uuid4(), uuid.uuid4()
    events = [
        plan(learner, at(2), session),
        step(EventType.STEP_COMPLETED, session, "shadow", AS_OF + timedelta(seconds=1)),
    ]

    report = compute_report(events, START, END, AS_OF)

    assert report.plan_completion.started == 1
    assert report.plan_completion.completed == 0
    assert report.mark_reuse is None
    assert report.repeat_failures is None
    with pytest.raises(ValueError):
        compute_report(events, END, START, AS_OF)
