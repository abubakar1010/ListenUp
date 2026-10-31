"""Shadow delivery measures from assessment signals (#82; FR-SH-4, FR-SH-9, AT-17).

Pure code: speech models only supply word timings and fillers, and every number
here comes from our own arithmetic. The transforms and their parameters live in a
versioned file that is provisional and uncalibrated (ADR 0092): they are
placeholders until the teacher golden set (#107/#110) calibrates them, never
approved scoring policy (ADR 0050). Times are seconds on one clock, the
recording's; the caller places the original's words on it.

Null is explicit. A measure that cannot be observed returns no score and a reason;
it never becomes a perfect or a zero score (ADR 0050).
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

PACKAGED_PARAMETERS = Path(__file__).with_name("shadow_delivery.v1.json")

# Measures this story computes; pronunciation and articulation follow in #83, and
# accent never enters the overall score (FR-SH-15).
MEASURES = ("timing", "fluency", "fillers", "completeness")


@dataclass(frozen=True)
class Word:
    """A reference word at `index` (reference_text.split()) and its timing."""

    index: int
    start: float
    end: float


@dataclass(frozen=True)
class Interval:
    start: float
    end: float


@dataclass(frozen=True)
class Measure:
    score: int | None
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EchoCheck:
    """`unchecked` means no detector ran; it never claims a clean recording."""

    status: Literal["unchecked", "clear", "leak"]
    message: Literal["use_headphones"] | None = None


@dataclass(frozen=True)
class DeliveryScores:
    measures: Mapping[str, Measure]
    overall: int | None
    overall_basis: tuple[str, ...]
    filler_count: int
    echo: EchoCheck
    parameters_version: str


def _invalid(key: str) -> ValueError:
    return ValueError(f"Invalid delivery parameter {key}")


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise _invalid(key)
    return value


def _number(section: Mapping[str, Any], key: str, *, above: float | None = None) -> float:
    """A finite number >= 0, or > `above` when given; bools are not numbers."""
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(key)
    if not math.isfinite(value) or value < 0 or (above is not None and not value > above):
        raise _invalid(key)
    return float(value)


def _weights(section: Mapping[str, Any], key: str, names: set[str], *, low: int) -> None:
    weights = section.get(key)
    if (
        not isinstance(weights, Mapping)
        or set(weights) != names
        or any(type(w) is not int or w < low for w in weights.values())
    ):
        raise _invalid(key)


def _validate(data: Mapping[str, Any]) -> None:
    timing = _section(data, "timing")
    words = timing.get("min_matched_words")
    if type(words) is not int or words < 2:  # ADR 0050: two unambiguous words
        raise _invalid("min_matched_words")
    _number(timing, "onset_zero_credit_s", above=_number(timing, "onset_full_credit_s"))
    _number(timing, "rate_zero", above=_number(timing, "rate_tolerance"))
    _number(timing, "break_s", above=0)
    _weights(timing, "weights", {"onsets", "rate", "phrasing"}, low=1)
    fluency = _section(data, "fluency")
    _number(fluency, "long_pause_s", above=_number(fluency, "hesitation_s", above=0))
    _weights(fluency, "event_weights", {"hesitation", "long_pause", "restart"}, low=0)
    _number(fluency, "zero_events_per_minute", above=0)
    fillers = _section(data, "fillers")
    _number(fillers, "zero_per_minute", above=_number(fillers, "free_per_minute"))
    if type(fillers.get("count_validated")) is not bool:
        raise _invalid("count_validated")
    threshold = _number(_section(data, "echo"), "leakage_threshold", above=0)
    if threshold > 1:
        raise _invalid("leakage_threshold")


@dataclass(frozen=True)
class DeliveryParameters:
    version: str
    provisional: bool
    calibrated: bool
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path = PACKAGED_PARAMETERS) -> "DeliveryParameters":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DeliveryParameters":
        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("Invalid delivery parameter version")
        if type(data.get("provisional")) is not bool or type(data.get("calibrated")) is not bool:
            raise ValueError("Invalid delivery parameter status")
        _validate(data)
        return cls(version, data["provisional"], data["calibrated"], data)


def _half_up(value: float) -> int:
    """Nearest integer, halves up, for the nonnegative values scored here."""
    return math.floor(value + 0.5)


def _completeness(reference_word_count: int, recorded: Sequence[Word]) -> Measure:
    found = {w.index for w in recorded if 0 <= w.index < reference_word_count}
    return Measure(
        # Integer arithmetic so 12.5 % is exactly a half and rounds up.
        (200 * len(found) + reference_word_count) // (2 * reference_word_count),
        details={"found": len(found), "reference": reference_word_count},
    )


def _credit(error: float, full: float, zero: float) -> float:
    """1 within `full`, 0 from `zero`, linear between."""
    if error <= full:
        return 1.0
    if error >= zero:
        return 0.0
    return (zero - error) / (zero - full)


def _pairs(recorded: Sequence[Word], original: Sequence[Word]) -> dict[int, tuple[Word, Word]]:
    """Pair the learner's words with the original's by dynamic time warping.

    The sequences are the learner's words in spoken order and the original's in
    reference order; a step costs 0 when both name the same reference word and 1
    otherwise, so the alignment follows word order, never timing, and cannot hide a
    late start. Among equally cheap alignments the backtrack prefers the diagonal,
    which pairs a restarted word with its final attempt; if a word is still paired
    more than once, the later utterance wins. The restart replaces the first try.
    """
    spoken = sorted(recorded, key=lambda w: (w.start, w.index))
    reference = sorted(original, key=lambda w: w.index)
    n, m = len(spoken), len(reference)
    if not n or not m:
        return {}
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            step = 0.0 if spoken[i - 1].index == reference[j - 1].index else 1.0
            cost[i][j] = step + min(cost[i - 1][j - 1], cost[i - 1][j], cost[i][j - 1])
    path: list[tuple[int, int]] = []
    i, j = n, m
    while i and j:
        path.append((i - 1, j - 1))
        # Deterministic tie-break: diagonal, then a repeated original word, then skip.
        choices = ((cost[i - 1][j - 1], 0), (cost[i - 1][j], 1), (cost[i][j - 1], 2))
        move = min(choices)[1]
        i, j = (i - 1, j - 1) if move == 0 else (i - 1, j) if move == 1 else (i, j - 1)
    pairs: dict[int, tuple[Word, Word]] = {}
    for a, b in reversed(path):  # spoken order, so a later pairing replaces an earlier one
        if spoken[a].index == reference[b].index:
            pairs[reference[b].index] = (spoken[a], reference[b])
    return pairs


def _timing(
    section: Mapping[str, Any], recorded: Sequence[Word], original: Sequence[Word]
) -> Measure:
    pairs = _pairs(recorded, original)
    if len(pairs) < max(2, int(section["min_matched_words"])):
        return Measure(None, "too_few_matched_words", {"matched": len(pairs)})
    ordered = [pairs[k] for k in sorted(pairs)]
    full, zero = section["onset_full_credit_s"], section["onset_zero_credit_s"]
    lags = [said.start - heard.start for said, heard in ordered]
    components = {"onsets": sum(_credit(abs(lag), full, zero) for lag in lags) / len(lags)}
    said_span = ordered[-1][0].start - ordered[0][0].start
    heard_span = ordered[-1][1].start - ordered[0][1].start
    ratio = said_span / heard_span if heard_span > 0 else None
    if ratio is not None:
        components["rate"] = _credit(
            abs(ratio - 1), section["rate_tolerance"], section["rate_zero"]
        )
    breaks = kept = 0
    for k in sorted(pairs):
        if k + 1 not in pairs:
            continue
        (said, heard), (said_next, heard_next) = pairs[k], pairs[k + 1]
        if heard_next.start - heard.end >= section["break_s"]:
            breaks += 1
            kept += said_next.start - said.end >= section["break_s"]
    if breaks:
        components["phrasing"] = kept / breaks
    weights = section["weights"]
    total = sum(weights[name] for name in components)
    value = sum(weights[name] * credit for name, credit in components.items()) / total
    return Measure(
        _half_up(100 * value),
        details={
            "matched": len(pairs),
            "mean_lag_s": round(sum(lags) / len(lags), 3),
            "mean_abs_lag_s": round(sum(map(abs, lags)) / len(lags), 3),
            "rate_ratio": None if ratio is None else round(ratio, 3),
            "breaks": breaks,
            "breaks_kept": kept,
        },
    )


def _original_minutes(original: Sequence[Word]) -> float | None:
    """Rates are per minute of the original passage, so rounds 1-3 on one segment
    compare like for like (FR-SH-12) and a learner's own pauses cannot dilute them."""
    if not original:
        return None
    seconds = max(w.end for w in original) - min(w.start for w in original)
    return seconds / 60 if seconds > 0 else None


def _fluency(
    section: Mapping[str, Any], recorded: Sequence[Word], original: Sequence[Word]
) -> Measure:
    minutes = _original_minutes(original)
    if minutes is None:
        return Measure(None, "no_original_timing")
    heard = {w.index: w for w in original}
    spoken = sorted(recorded, key=lambda w: (w.start, w.index))
    hesitations = long_pauses = restarts = 0
    for before, after in pairwise(spoken):
        if after.index <= before.index:
            restarts += after.index < before.index
            continue
        if before.index not in heard or after.index not in heard:
            continue  # unknown original gap: not judged (ADR 0050)
        expected = heard[after.index].start - heard[before.index].end
        excess = (after.start - before.end) - max(0.0, expected)
        if excess >= section["long_pause_s"]:
            long_pauses += 1
        elif excess >= section["hesitation_s"]:
            hesitations += 1
    weights = section["event_weights"]
    events = (
        weights["hesitation"] * hesitations
        + weights["long_pause"] * long_pauses
        + weights["restart"] * restarts
    )
    rate = events / minutes
    return Measure(
        _half_up(100 * _credit(rate, 0, section["zero_events_per_minute"])),
        details={
            "hesitations": hesitations,
            "long_pauses": long_pauses,
            "restarts": restarts,
            "events_per_minute": round(rate, 3),
        },
    )


def _fillers(
    section: Mapping[str, Any], fillers: Sequence[Interval], original: Sequence[Word]
) -> Measure:
    """Counted from the transcription that keeps disfluencies; an estimate until B4
    (#22) validates recall (AT-17, ADR 0050)."""
    minutes = _original_minutes(original)
    if minutes is None:
        return Measure(None, "no_original_timing")
    rate = len(fillers) / minutes
    credit = _credit(rate, section["free_per_minute"], section["zero_per_minute"])
    return Measure(
        _half_up(100 * credit),
        details={
            "count": len(fillers),
            "per_minute": round(rate, 3),
            "estimate": not section["count_validated"],
        },
    )


def _echo(section: Mapping[str, Any], leakage: float | None) -> EchoCheck:
    """Plumbing only: the leakage detector and its reliability are #80's (ADR 0092).

    A flagged round keeps its numbers; the learner is asked to use headphones.
    """
    if leakage is None:
        return EchoCheck("unchecked")
    if not 0 <= leakage <= 1:  # also refuses NaN
        raise ValueError("Invalid leakage signal")
    if leakage >= section["leakage_threshold"]:
        return EchoCheck("leak", "use_headphones")
    return EchoCheck("clear")


def score_round(
    parameters: DeliveryParameters,
    *,
    reference_word_count: int,
    original: Sequence[Word],
    recorded: Sequence[Word],
    fillers: Sequence[Interval],
    leakage: float | None,
) -> DeliveryScores:
    echo = _echo(parameters.raw["echo"], leakage)
    matched = [w for w in recorded if 0 <= w.index < reference_word_count]
    unobservable = (
        "no_reference_words"
        if reference_word_count <= 0
        else None
        if matched
        else "no_matched_words"
    )
    if unobservable:
        empty = {name: Measure(None, unobservable) for name in MEASURES}
        return DeliveryScores(empty, None, (), len(fillers), echo, parameters.version)
    measures = {
        "timing": _timing(parameters.raw["timing"], matched, original),
        "fluency": _fluency(parameters.raw["fluency"], matched, original),
        "fillers": _fillers(parameters.raw["fillers"], fillers, original),
        "completeness": _completeness(reference_word_count, recorded),
    }
    # FR-SH-9's equal weights over what is observable; accent is never included
    # (FR-SH-15) and #83 adds pronunciation and articulation (ADR 0092).
    basis = tuple(name for name in MEASURES if measures[name].score is not None)
    total = sum(measures[name].score or 0 for name in basis)
    overall = (2 * total + len(basis)) // (2 * len(basis)) if basis else None
    return DeliveryScores(measures, overall, basis, len(fillers), echo, parameters.version)


def place_original(
    words: Sequence[tuple[int, int, int]],
    *,
    segment: tuple[int, int],
    playback_offset_ms: int,
) -> list[Word]:
    """Put the original's words, `(segment word index, start ms, end ms)` in media
    time, on the recording's clock (ADR 0093).

    `playback_offset_ms` is where the original began in the recording, as the browser
    reported it: after the count-in, or later when autoplay waited for "Play now".
    Words not wholly inside the half-open segment were not played and are dropped.
    """
    if type(playback_offset_ms) is not int or playback_offset_ms < 0:
        raise ValueError("Invalid playback offset")
    left, right = segment
    return [
        Word(
            index,
            (start - left + playback_offset_ms) / 1000,
            (end - left + playback_offset_ms) / 1000,
        )
        for index, start, end in words
        if left <= start and end <= right
    ]
