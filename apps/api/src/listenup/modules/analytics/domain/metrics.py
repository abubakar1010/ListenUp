"""The five success metrics of PRD 2, computed from analytics events (#101, ADR 0033).

Pure functions over a list of events, so each definition is tested on hand-built
events. A report covers a date range [start, end): the cohort (plans, clips, learners
or marks) is chosen by when its first event happened in the range, and what happened
to it afterwards counts up to `as_of` (when the report runs), even after `end`.

- Plan completion rate: of the plans started in the range, how many reached the final
  step (Shadow opened, the PRD's definition) and how many completed it (Shadow done
  or skipped, SH-6).
- Time to first listen: for clips added in the range, the time from `content_added`
  to the first `listen_started` on that clip; median, 90th percentile and how many
  were under 60 s. Clips not yet listened to are counted, not timed.
- Return rate: of the learners whose first plan started in the range, how many started
  3 or more plans within 14 days of it. Learners still inside their 14 days who have
  not yet returned are reported apart and left out of the rate.
- Mark reuse: cards created plus Shadow segments (a session with a Shadow round), per
  session that reached Transcript in the range. No data for a range that ends before
  the first card or Shadow round was recorded.
- Repeat-failure trend: the share of marks made in the range whose pattern the learner
  had already marked, earlier in time, in another session; by session number 1 to 8
  (the learner's nth plan). Several sessions can be open at once, so "earlier" is when
  the mark was made, not which plan started first. A mark whose session has no
  `plan_started` event (a session from before event recording began) counts in the
  totals but has no session number. No data until marks exist.
"""

import math
import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from listenup.modules.analytics.domain.events import EventType

RETURN_WINDOW = timedelta(days=14)
RETURN_SESSIONS = 3
FIRST_LISTEN_TARGET_S = 60.0
TREND_SESSIONS = 8

# What the report reads, so the repository can leave the rest in the table: every
# metric ignores the other event types, and the only steps it looks at are these.
REPORT_EVENT_TYPES = (
    EventType.CONTENT_ADDED,
    EventType.PLAN_STARTED,
    EventType.STEP_STARTED,
    EventType.STEP_COMPLETED,
    EventType.LISTEN_STARTED,
    EventType.MARK_CREATED,
    EventType.CARD_CREATED,
    EventType.SHADOW_ROUND_COMPLETED,
)
REPORT_STEPS = ("transcript", "shadow")


@dataclass(frozen=True)
class Event:
    type: EventType
    user_id: uuid.UUID
    subject_id: uuid.UUID
    occurred_at: datetime
    step: str | None = None
    content_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


@dataclass(frozen=True)
class PlanCompletion:
    started: int
    reached_final_step: int
    completed: int

    @property
    def reach_rate(self) -> float | None:
        return _rate(self.reached_final_step, self.started)

    @property
    def completion_rate(self) -> float | None:
        return _rate(self.completed, self.started)


@dataclass(frozen=True)
class FirstListen:
    clips_added: int
    listened: int
    median_seconds: float | None
    p90_seconds: float | None
    under_target: int

    @property
    def under_target_rate(self) -> float | None:
        return _rate(self.under_target, self.listened)


@dataclass(frozen=True)
class ReturnRate:
    new_learners: int
    returned: int
    window_open: int

    @property
    def rate(self) -> float | None:
        return _rate(self.returned, self.new_learners - self.window_open)


@dataclass(frozen=True)
class MarkReuse:
    sessions_reached_transcript: int
    cards: int
    shadow_segments: int

    @property
    def rate(self) -> float | None:
        return _rate(self.cards + self.shadow_segments, self.sessions_reached_transcript)


@dataclass(frozen=True)
class SessionShare:
    session_number: int
    marks: int
    repeats: int

    @property
    def share(self) -> float | None:
        return _rate(self.repeats, self.marks)


@dataclass(frozen=True)
class RepeatFailureTrend:
    marks: int
    repeats: int
    by_session: tuple[SessionShare, ...]
    unnumbered: int = 0  # marks (in `marks`) whose session has no plan_started event

    @property
    def share(self) -> float | None:
        return _rate(self.repeats, self.marks)


@dataclass(frozen=True)
class Report:
    start: datetime
    end: datetime
    as_of: datetime
    plan_completion: PlanCompletion
    first_listen: FirstListen
    return_rate: ReturnRate
    mark_reuse: MarkReuse | None  # None: no card or Shadow round recorded before `end`
    repeat_failures: RepeatFailureTrend | None  # None: no marks in the range


def _in(event: Event, start: datetime, end: datetime) -> bool:
    return start <= event.occurred_at < end


def _of(events: Iterable[Event], kind: EventType) -> list[Event]:
    return [e for e in events if e.type is kind]


def _sessions_with_step(events: list[Event], kind: EventType, step: str) -> set[uuid.UUID]:
    return {e.subject_id for e in events if e.type is kind and e.step == step}


def plan_completion(events: list[Event], start: datetime, end: datetime) -> PlanCompletion:
    cohort = {e.subject_id for e in _of(events, EventType.PLAN_STARTED) if _in(e, start, end)}
    reached = _sessions_with_step(events, EventType.STEP_STARTED, "shadow")
    completed = _sessions_with_step(events, EventType.STEP_COMPLETED, "shadow")
    return PlanCompletion(len(cohort), len(cohort & reached), len(cohort & completed))


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a sorted, non-empty list."""
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def first_listen(events: list[Event], start: datetime, end: datetime) -> FirstListen:
    listens: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = defaultdict(list)
    for e in _of(events, EventType.LISTEN_STARTED):
        if e.content_id is not None:
            listens[(e.user_id, e.content_id)].append(e.occurred_at)
    added = [e for e in _of(events, EventType.CONTENT_ADDED) if _in(e, start, end)]
    waits: list[float] = []
    for e in added:
        later = [t for t in listens.get((e.user_id, e.subject_id), []) if t >= e.occurred_at]
        if later:
            waits.append((min(later) - e.occurred_at).total_seconds())
    waits.sort()
    return FirstListen(
        clips_added=len(added),
        listened=len(waits),
        median_seconds=statistics.median(waits) if waits else None,
        p90_seconds=_percentile(waits, 0.9) if waits else None,
        under_target=sum(1 for w in waits if w < FIRST_LISTEN_TARGET_S),
    )


def _plans_by_learner(events: list[Event]) -> dict[uuid.UUID, list[Event]]:
    plans: dict[uuid.UUID, list[Event]] = defaultdict(list)
    for e in _of(events, EventType.PLAN_STARTED):
        plans[e.user_id].append(e)
    for started in plans.values():
        started.sort(key=lambda e: (e.occurred_at, e.subject_id))
    return plans


def return_rate(events: list[Event], start: datetime, end: datetime, as_of: datetime) -> ReturnRate:
    new = returned = window_open = 0
    for started in _plans_by_learner(events).values():
        first = started[0].occurred_at
        if not start <= first < end:
            continue
        new += 1
        closes = first + RETURN_WINDOW
        if sum(1 for e in started if e.occurred_at < closes) >= RETURN_SESSIONS:
            returned += 1
        elif closes > as_of:
            window_open += 1
    return ReturnRate(new, returned, window_open)


def mark_reuse(events: list[Event], start: datetime, end: datetime) -> MarkReuse | None:
    cards = _of(events, EventType.CARD_CREATED)
    rounds = _of(events, EventType.SHADOW_ROUND_COMPLETED)
    if not any(e.occurred_at < end for e in cards + rounds):
        return None
    reached = {
        e.subject_id
        for e in _of(events, EventType.STEP_STARTED)
        if e.step == "transcript" and _in(e, start, end)
    }
    return MarkReuse(
        sessions_reached_transcript=len(reached),
        cards=sum(1 for e in cards if e.session_id in reached),
        shadow_segments=len({e.session_id for e in rounds if e.session_id in reached}),
    )


def repeat_failures(
    events: list[Event], start: datetime, end: datetime
) -> RepeatFailureTrend | None:
    marks = sorted(_of(events, EventType.MARK_CREATED), key=lambda e: (e.occurred_at, e.subject_id))
    if not any(_in(e, start, end) for e in marks):
        return None
    numbers = {
        plan.subject_id: number
        for started in _plans_by_learner(events).values()
        for number, plan in enumerate(started, start=1)
    }
    sessions_by_pattern: dict[tuple[uuid.UUID, str], set[uuid.UUID | None]] = defaultdict(set)
    counted: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # number -> [marks, repeats]
    total = repeats = unnumbered = 0
    for e in marks:
        pattern = e.properties.get("pattern")
        seen_in = sessions_by_pattern[(e.user_id, str(pattern))] if pattern else set()
        repeat = bool(seen_in - {e.session_id})
        if pattern:
            seen_in.add(e.session_id)
        if not _in(e, start, end):
            continue
        total += 1
        repeats += repeat
        number = numbers.get(e.session_id) if e.session_id else None
        if number is None:
            unnumbered += 1
        elif number <= TREND_SESSIONS:
            counted[number][0] += 1
            counted[number][1] += repeat
    by_session = tuple(
        SessionShare(n, counted[n][0], counted[n][1]) for n in range(1, TREND_SESSIONS + 1)
    )
    return RepeatFailureTrend(total, repeats, by_session, unnumbered)


def compute_report(events: list[Event], start: datetime, end: datetime, as_of: datetime) -> Report:
    """The five metrics for [start, end), following events up to `as_of`."""
    if end <= start:
        raise ValueError("the range must end after it starts")
    seen = [e for e in events if e.occurred_at < as_of]
    return Report(
        start=start,
        end=end,
        as_of=as_of,
        plan_completion=plan_completion(seen, start, end),
        first_listen=first_listen(seen, start, end),
        return_rate=return_rate(seen, start, end, as_of),
        mark_reuse=mark_reuse(seen, start, end),
        repeat_failures=repeat_failures(seen, start, end),
    )
