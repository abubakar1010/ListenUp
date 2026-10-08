"""The product events of PRD 8.2 and the rules for what each one means (ADR 0033).

Pure: no framework, database or network code. The analytics service turns these into
rows; other modules never build events themselves.

Meanings:
- `content_added`: a new content item exists (an upload confirmed; YouTube intake
  later), with its `source_type`.
- `plan_started`: a session was created, with its entry `path`.
- `step_started`: the plan moved onto a step: the first step at plan start, then each
  step that opens when the one before it is finished. At most once per session and
  step, so a step reopened by an entry change counts once.
- `step_completed`: a step was finished, with `outcome` done or skipped.
- `listen_started`: an attempt at Blind or Dictation began (Blind: the learner pressed
  start; Dictation: the player opened). Not in PRD 8.2's list; "time to first listen"
  (PRD 2) needs it.
- `dictation_replays`: how often the learner replayed during one Dictation attempt.
  Fires once Dictation submission (#53) reports the count.
- `blind_abandoned`: a Blind attempt was voided (left, reloaded, seeked, too many
  interruptions ...), with the `reason`. Only voids the server sees are recorded: the
  browser's report or a late heartbeat. An attempt whose browser vanished without
  either stays active and is not counted until the learner next acts on it.
- `mark_created`, `card_created`, `shadow_round_completed`: fire once marks, cards and
  Shadow exist. A mark carries a hash of its normalised phrase, never the phrase.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class EventType(StrEnum):
    CONTENT_ADDED = "content_added"
    PLAN_STARTED = "plan_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    LISTEN_STARTED = "listen_started"
    DICTATION_REPLAYS = "dictation_replays"
    BLIND_ABANDONED = "blind_abandoned"
    MARK_CREATED = "mark_created"
    CARD_CREATED = "card_created"
    SHADOW_ROUND_COMPLETED = "shadow_round_completed"


STEPS = ("blind", "dictation", "transcript", "card", "shadow")
SOURCE_TYPES = ("upload", "youtube")
PATHS = ("blind", "dictation", "both")
LISTEN_MODES = ("blind", "dictation")
OPEN = "open"
FINISHED = ("done", "skipped")


@dataclass(frozen=True)
class StepChange:
    """A step event that a change of the plan's step statuses implies."""

    event: EventType
    step: str
    outcome: str | None = None  # 'done' or 'skipped' for STEP_COMPLETED


def step_changes(before: Mapping[str, str], after: Mapping[str, str]) -> list[StepChange]:
    """The step events between two snapshots of a plan, as {step: status}.

    A step that becomes open has started; a step that becomes done or skipped has
    completed. A step missing from `before` (a new plan, or a step an entry change
    added) counts as locked. Steps an entry change removed are ignored.
    """
    changes: list[StepChange] = []
    for step, status in after.items():
        if step not in STEPS:
            raise ValueError(f"unknown step {step!r}")
        was = before.get(step)
        if status in FINISHED and was not in FINISHED:
            changes.append(StepChange(EventType.STEP_COMPLETED, step, status))
        elif status == OPEN and was != OPEN:
            changes.append(StepChange(EventType.STEP_STARTED, step))
    return changes


_WORDS = re.compile(r"[a-z0-9']+")


def mark_pattern(phrase: str) -> str:
    """A stable key for a marked phrase, so repeat failures can be matched (PRD 2).

    The phrase is lowercased and reduced to its words ("Could've," and "could've"
    match), then hashed: the event never stores what the learner marked.
    """
    words = " ".join(_WORDS.findall(phrase.lower().replace("\u2019", "'")))
    if not words:
        raise ValueError("a mark's phrase has no words")
    return hashlib.sha256(words.encode()).hexdigest()[:32]


def require_one_of(name: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, not {value!r}")
    return value
