"""Pronunciation, articulation, accent and word labels for a Shadow round (#83).

FR-SH-9, FR-SH-10, FR-SH-15. Pure code over the speech-assessment port's signals,
passed in as plain values: the port supplies per-sound scores, word timings and
pitch, and every number here comes from our own arithmetic. Thresholds and weights
live in a versioned, provisional and uncalibrated file (ADR 0099); they are
placeholders until the teacher golden set (#107/#110) calibrates them, never
approved scoring policy (ADR 0050).

Null is explicit: a measure that cannot be observed returns no score and a reason.
Accent is guidance compared with this speaker, labelled experimental, and never
enters the overall round score (D11).
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from listenup.modules.grading.domain.delivery import (
    DeliveryParameters,
    EchoCheck,
    Interval,
    Measure,
    Word,
    frozen_copy,
    half_up,
    overall_score,
    score_round,
)

PACKAGED_SPEECH_PARAMETERS = Path(__file__).with_name("shadow_speech.v1.json")

# The six measures in the overall round score; accent is guidance only (D11).
SCORED_MEASURES = ("timing", "pronunciation", "articulation", "fluency", "fillers", "completeness")
ARTICULATION_ISSUES = ("dropped", "merged", "unclear")

Issue = Literal["dropped", "merged", "unclear", "inaccurate"]
Position = Literal["initial", "medial", "final"]
Label = Literal["good", "needs_work", "missed"]


@dataclass(frozen=True)
class Sound:
    """A provider-labelled sound with normalized goodness in [0, 1]."""

    label: str
    start: float
    end: float
    score: float


@dataclass(frozen=True)
class SpokenWord:
    """A reference word at `index` the learner said, with its ordered sounds."""

    index: int
    start: float
    end: float
    accuracy: float
    sounds: tuple[Sound, ...]


@dataclass(frozen=True)
class SoundReason:
    sound: str
    position: Position
    issue: Issue
    linking: bool


@dataclass(frozen=True)
class WordLabel:
    """`basis` says whether the score came from the word's sounds or, when the
    provider gave none, from its word-level accuracy."""

    index: int
    text: str
    label: Label
    score: int | None
    basis: Literal["sounds", "word"] | None
    reasons: tuple[SoundReason, ...]


SECTION_KEYS = {
    "sounds": {"dropped_below", "unclear_below", "merged_max_s", "linking_gap_s"},
    "labels": {"good_from"},
    "articulation": {"position_weights", "linking_weight", "issue_weights"},
    "accent": {
        "experimental",
        "weights",
        "min_words",
        "zero_r",
        "full_r",
        "vowel_labels",
        "vowel_full_gap",
        "vowel_zero_gap",
    },
    "overall": {"weights"},
}
TOP_KEYS = {"version", "provisional", "calibrated", *SECTION_KEYS}


@dataclass(frozen=True)
class SpeechParameters:
    version: str
    provisional: bool
    calibrated: bool
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path = PACKAGED_SPEECH_PARAMETERS) -> "SpeechParameters":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SpeechParameters":
        if not isinstance(data, Mapping) or set(data) != TOP_KEYS:
            raise ValueError("Invalid speech parameter keys")
        version = data["version"]
        if not isinstance(version, str) or not version:
            raise _invalid("version")
        if type(data["provisional"]) is not bool or type(data["calibrated"]) is not bool:
            raise _invalid("status")
        _validate(data)
        # A frozen copy, so nothing changes the values after they were validated.
        return cls(version, data["provisional"], data["calibrated"], frozen_copy(data))


def _invalid(key: str) -> ValueError:
    return ValueError(f"Invalid speech parameter {key}")


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data[key]
    if not isinstance(value, Mapping) or set(value) != SECTION_KEYS[key]:
        raise _invalid(key)
    return value


def _number(section: Mapping[str, Any], key: str, low: float, high: float) -> float:
    """A finite number in [low, high]; bools are not numbers."""
    value: object = section[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(key)
    if not math.isfinite(value) or not low <= value <= high:
        raise _invalid(key)
    return float(value)


def _above(section: Mapping[str, Any], key: str, floor: float, high: float) -> float:
    value = _number(section, key, floor, high)
    if not value > floor:
        raise _invalid(key)
    return value


def _weights(section: Mapping[str, Any], key: str, names: Sequence[str]) -> None:
    weights = section[key]
    if (
        not isinstance(weights, Mapping)
        or set(weights) != set(names)
        or any(type(w) is not int or w < 1 for w in weights.values())
    ):
        raise _invalid(key)


def _validate(data: Mapping[str, Any]) -> None:
    sounds = _section(data, "sounds")
    unclear = _number(sounds, "unclear_below", 0, 1)
    dropped = _number(sounds, "dropped_below", 0, 1)
    if not dropped < unclear:
        raise _invalid("dropped_below")
    _above(sounds, "merged_max_s", 0, math.inf)
    _above(sounds, "linking_gap_s", 0, math.inf)
    good_from = _number(_section(data, "labels"), "good_from", 0, 1)
    if good_from < unclear:  # a word with an unclear sound is never good
        raise _invalid("good_from")
    articulation = _section(data, "articulation")
    _weights(articulation, "position_weights", ("initial", "medial", "final"))
    if type(articulation["linking_weight"]) is not int or articulation["linking_weight"] < 1:
        raise _invalid("linking_weight")
    issues = articulation["issue_weights"]
    if not isinstance(issues, Mapping) or set(issues) != set(ARTICULATION_ISSUES):
        raise _invalid("issue_weights")
    for name in ARTICULATION_ISSUES:
        _above(issues, name, 0, 1)
    accent = _section(data, "accent")
    if type(accent["experimental"]) is not bool:
        raise _invalid("experimental")
    _weights(accent, "weights", ("vowels", "stress", "pitch"))
    if type(accent["min_words"]) is not int or accent["min_words"] < 3:
        raise _invalid("min_words")  # two points always correlate perfectly
    zero_r = _number(accent, "zero_r", -1, 1)
    _above(accent, "full_r", zero_r, 1)
    labels = accent["vowel_labels"]
    if (
        not isinstance(labels, list)
        or not labels
        or any(not isinstance(label, str) or not label for label in labels)
    ):
        raise _invalid("vowel_labels")
    full_gap = _number(accent, "vowel_full_gap", 0, 1)
    _above(accent, "vowel_zero_gap", full_gap, 1)
    # D11: exactly the six scored measures, so accent can never be weighted in.
    _weights(_section(data, "overall"), "weights", SCORED_MEASURES)


# --- Shared sound annotation -------------------------------------------------------


@dataclass(frozen=True)
class _Annotated:
    sound: Sound
    position: Position
    linking: bool
    issue: Issue | None


def _said(words: Sequence[SpokenWord], reference_word_count: int) -> dict[int, SpokenWord]:
    """One attempt per reference word: the last in spoken order, so a restart
    replaces the first try (as in timing, ADR 0092)."""
    said: dict[int, SpokenWord] = {}
    for w in sorted(words, key=lambda w: (w.start, w.index)):
        if 0 <= w.index < reference_word_count:
            said[w.index] = w
    return said


def _issue(section: Mapping[str, Any], good_from: float, sound: Sound) -> Issue | None:
    if sound.score < section["dropped_below"]:
        return "dropped"
    if sound.score < section["unclear_below"]:
        # A sound squeezed into its neighbour: too short to stand on its own. The
        # length is rounded to nine places, as the linking gap is, so a sound of
        # exactly `merged_max_s` in decimals is never merged by binary error.
        short = round(sound.end - sound.start, 9) < section["merged_max_s"]
        return "merged" if short else "unclear"
    if sound.score < good_from:
        return "inaccurate"
    return None


def _annotate(
    parameters: SpeechParameters, said: Mapping[int, SpokenWord]
) -> dict[int, list[_Annotated]]:
    """Each sound's place in its word, whether it sits on a linking boundary (the
    next reference word follows with less than `linking_gap_s` of silence) and its
    issue, so articulation and the word markers flag exactly the same sounds."""
    section = parameters.raw["sounds"]
    good_from = parameters.raw["labels"]["good_from"]
    linked_after = _links(parameters, said)
    annotated: dict[int, list[_Annotated]] = {}
    for k, w in said.items():
        last = len(w.sounds) - 1
        annotated[k] = [
            _Annotated(
                s,
                "final" if i == last else "initial" if i == 0 else "medial",
                (i == last and k in linked_after) or (i == 0 and k - 1 in linked_after),
                _issue(section, good_from, s),
            )
            for i, s in enumerate(w.sounds)
        ]
    return annotated


def _links(parameters: SpeechParameters, said: Mapping[int, SpokenWord]) -> set[int]:
    """Words whose next reference word follows with under `linking_gap_s` of silence.

    Gaps are rounded to nine places first, so a gap of exactly the threshold in
    decimals (0.35 - 0.3) is never lost to binary error and does not link.
    """
    gap = parameters.raw["sounds"]["linking_gap_s"]
    return {
        k for k, w in said.items() if k + 1 in said and round(said[k + 1].start - w.end, 9) < gap
    }


def _word_value(w: SpokenWord) -> float:
    """Goodness of pronunciation per sound, averaged per word; the word-level
    accuracy only when the provider gave no sounds."""
    if not w.sounds:
        return w.accuracy
    return sum(s.score for s in w.sounds) / len(w.sounds)


# --- Measures ----------------------------------------------------------------------


def pronunciation(
    parameters: SpeechParameters, words: Sequence[SpokenWord], *, reference_word_count: int
) -> Measure:
    """Mean of the per-word values over the words said. A missed word is
    completeness's, so it is not counted twice."""
    said = _said(words, reference_word_count)
    if not said:
        return Measure(None, "no_matched_words")
    values = [_word_value(w) for w in said.values()]
    return Measure(
        half_up(100 * sum(values) / len(values)),
        details={
            "judged_words": len(values),
            "word_accuracy_only": sum(1 for w in said.values() if not w.sounds),
        },
    )


def articulation(
    parameters: SpeechParameters, words: Sequence[SpokenWord], *, reference_word_count: int
) -> Measure:
    """Dropped, merged and unclear sounds, weighted towards word endings and
    linking boundaries: 1 - weighted penalties / weighted sounds."""
    said = _said(words, reference_word_count)
    if not said:
        return Measure(None, "no_matched_words")
    section = parameters.raw["articulation"]
    sounds = [a for group in _annotate(parameters, said).values() for a in group]
    if not sounds:
        return Measure(None, "no_sound_evidence")
    total = penalty = 0.0
    for a in sounds:
        weight = section["position_weights"][a.position]
        if a.linking:
            weight = max(weight, section["linking_weight"])
        total += weight
        if a.issue in ARTICULATION_ISSUES:
            penalty += weight * section["issue_weights"][a.issue]
    details: dict[str, int] = {"sounds": len(sounds)}
    for name in ARTICULATION_ISSUES:
        details[name] = sum(1 for a in sounds if a.issue == name)
    details["linked"] = len(_links(parameters, said))
    return Measure(half_up(100 * (1 - penalty / total)), details=details)


# --- Word labels (FR-SH-10) --------------------------------------------------------


def label_words(
    parameters: SpeechParameters,
    reference_words: Sequence[str],
    words: Sequence[SpokenWord],
) -> list[WordLabel]:
    """Every segment word, in order: missed when not heard, needs work when its
    score is under `good_from` or any of its sounds has an issue, otherwise good."""
    said = _said(words, len(reference_words))
    annotated = _annotate(parameters, said)
    good_from = parameters.raw["labels"]["good_from"]
    labels: list[WordLabel] = []
    for index, text in enumerate(reference_words):
        w = said.get(index)
        if w is None:
            labels.append(WordLabel(index, text, "missed", None, None, ()))
            continue
        value = _word_value(w)
        reasons = tuple(
            SoundReason(a.sound.label, a.position, a.issue, a.linking)
            for a in annotated[index]
            if a.issue is not None
        )
        label: Label = "good" if value >= good_from and not reasons else "needs_work"
        labels.append(
            WordLabel(
                index,
                text,
                label,
                half_up(100 * value),
                "sounds" if w.sounds else "word",
                reasons,
            )
        )
    return labels


# --- Accent (FR-SH-15) -------------------------------------------------------------


@dataclass(frozen=True)
class Prosody:
    """One word's duration and median voiced pitch (cents; None if unvoiced)."""

    duration_s: float
    pitch_cents: float | None


def hertz_to_cents(hertz: float | None) -> float | None:
    """Cents above 1 Hz, the reference profile's unit; unvoiced stays None."""
    return None if hertz is None else 1200 * math.log2(hertz)


def word_pitch(
    points: Sequence[tuple[float, float | None]], start: float, end: float
) -> float | None:
    """Median of the voiced points in the half-open word span [start, end)."""
    voiced = sorted(p for t, p in points if start <= t < end and p is not None)
    if not voiced:
        return None
    middle = len(voiced) // 2
    return voiced[middle] if len(voiced) % 2 else (voiced[middle - 1] + voiced[middle]) / 2


def prosody_from_frames(
    words: Sequence[tuple[int, int, int]],
    *,
    frames_start_ms: int,
    frame_step_ms: int,
    pitch_cents: Sequence[int | None],
) -> dict[int, Prosody]:
    """The original's `(index, start ms, end ms)` words, in media time, with the
    median voiced pitch of the reference profile's frames inside each word.

    `frames_start_ms` is where the profile's span starts. Its frames are centred,
    frame i at `frames_start_ms + (i + 1/2) * frame_step_ms` (the acoustics
    extractor's fixed frame centres), so each frame counts for the word its centre
    falls in.
    """
    points = [
        (frames_start_ms + (i + 0.5) * frame_step_ms, None if cents is None else float(cents))
        for i, cents in enumerate(pitch_cents)
    ]
    return {
        index: Prosody((end - start) / 1000, word_pitch(points, start, end))
        for index, start, end in words
    }


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson r of the learner (xs) against the original (ys): invariant to each
    speaker's register, range and pace. None when the original is flat; a flat
    learner against a varied original is 0, no agreement."""
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    syy = sum(d * d for d in dy)
    if round(syy, 9) == 0:
        return None
    sxx = sum(d * d for d in dx)
    if round(sxx, 9) == 0:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / math.sqrt(sxx * syy)


def _agreement(
    section: Mapping[str, Any], pairs: Sequence[tuple[float, float]], too_few: str
) -> tuple[float | None, str | None]:
    if len(pairs) < section["min_words"]:
        return None, too_few
    r = _correlation([a for a, _ in pairs], [b for _, b in pairs])
    if r is None:
        return None, "flat_original"
    low, high = section["zero_r"], section["full_r"]
    return (0.0 if r <= low else 1.0 if r >= high else (r - low) / (high - low)), None


def _vowels(
    section: Mapping[str, Any],
    spoken: Mapping[int, SpokenWord],
    reference_sounds: Mapping[int, Sequence[Sound]] | None,
) -> tuple[float | None, str | None]:
    """Each vowel's goodness against the same vowel in this speaker's own word:
    only a shortfall counts, so sounding clearer than the speaker is never wrong."""
    if reference_sounds is None:
        return None, "no_reference_sounds"
    vowels = set(section["vowel_labels"])
    full, zero = section["vowel_full_gap"], section["vowel_zero_gap"]
    credits: list[float] = []
    for index, w in spoken.items():
        for mine, theirs in zip(w.sounds, reference_sounds.get(index, ()), strict=False):
            if mine.label == theirs.label and mine.label in vowels:
                shortfall = round(max(0.0, theirs.score - mine.score), 9)
                credits.append(
                    1.0
                    if shortfall <= full
                    else 0.0
                    if shortfall >= zero
                    else (zero - shortfall) / (zero - full)
                )
    if not credits:
        return None, "no_vowels_compared"
    return sum(credits) / len(credits), None


def accent(
    parameters: SpeechParameters,
    learner: Mapping[int, Prosody],
    original: Mapping[int, Prosody],
    *,
    spoken: Sequence[SpokenWord] = (),
    reference_sounds: Mapping[int, Sequence[Sound]] | None = None,
) -> Measure:
    """Experimental guidance compared with this speaker, never correctness.

    - vowels: vowel goodness against the speaker's own vowels. The reference
      profile holds no sounds yet (phone-level reference GOP is #80's, ADR 0050),
      so this is unobserved until a caller supplies `reference_sounds`.
    - stress: agreement of the words' relative lengths (log durations), i.e.
      which words the speaker leans on; the contract has no syllables.
    - pitch: agreement of the words' median pitch, i.e. the contour.

    Components with nothing to observe drop out and the weights renormalize.
    """
    section = parameters.raw["accent"]
    common = sorted(set(learner) & set(original))
    stress_pairs = [
        (math.log(learner[k].duration_s), math.log(original[k].duration_s))
        for k in common
        if learner[k].duration_s > 0 and original[k].duration_s > 0
    ]
    pitch_pairs = [
        (mine, theirs)
        for k in common
        if (mine := learner[k].pitch_cents) is not None
        and (theirs := original[k].pitch_cents) is not None
    ]
    said = {w.index: w for w in sorted(spoken, key=lambda w: (w.start, w.index))}
    found = {
        "vowels": _vowels(section, said, reference_sounds),
        "stress": _agreement(section, stress_pairs, "too_few_words"),
        "pitch": _agreement(section, pitch_pairs, "too_few_voiced_words"),
    }
    components = {name: value for name, (value, _) in found.items()}
    unobserved = {name: reason for name, (_, reason) in found.items() if reason}
    details = {
        "experimental": section["experimental"],
        "compared_with": "this_speaker",
        "components": components,
        "unobserved": unobserved,
    }
    weights = section["weights"]
    observed = {name: value for name, value in components.items() if value is not None}
    if not observed:
        return Measure(None, "no_accent_evidence", details)
    total = sum(weights[name] for name in observed)
    value = sum(weights[name] * credit for name, credit in observed.items()) / total
    return Measure(half_up(100 * value), details=details)


# --- The whole round ---------------------------------------------------------------


@dataclass(frozen=True)
class RoundGrade:
    """All seven measures, the overall over the six scored ones, every word's label
    and the two parameter versions that produced them (FR-SH-9, FR-SH-10, FR-SH-18)."""

    measures: Mapping[str, Measure]
    overall: int | None
    overall_basis: tuple[str, ...]
    overall_weights: Mapping[str, int]
    word_labels: list[WordLabel]
    filler_count: int
    echo: EchoCheck
    delivery_version: str
    speech_version: str


def grade_round(
    delivery: DeliveryParameters,
    parameters: SpeechParameters,
    *,
    reference_words: Sequence[str],
    original: Sequence[Word],
    spoken: Sequence[SpokenWord],
    fillers: Sequence[Interval],
    leakage: float | None,
    clock_known: bool,
    learner_pitch: Sequence[tuple[float, float | None]],
    original_prosody: Mapping[int, Prosody],
    reference_sounds: Mapping[int, Sequence[Sound]] | None = None,
) -> RoundGrade:
    """`original` is on the recording's clock (timing only); `original_prosody` and
    `learner_pitch` (seconds, cents) compare word by word, so they need no shared
    clock. `reference_sounds` stays None until the profile has phone scores (#80)."""
    count = len(reference_words)
    delivered = score_round(
        delivery,
        reference_word_count=count,
        original=original,
        recorded=[Word(w.index, w.start, w.end) for w in spoken],
        fillers=fillers,
        leakage=leakage,
        clock_known=clock_known,
    )
    said = _said(spoken, count)
    learner = {
        k: Prosody(w.end - w.start, word_pitch(learner_pitch, w.start, w.end))
        for k, w in said.items()
    }
    measures: dict[str, Measure] = dict(delivered.measures)
    if said:
        measures["pronunciation"] = pronunciation(parameters, spoken, reference_word_count=count)
        measures["articulation"] = articulation(parameters, spoken, reference_word_count=count)
        measures["accent"] = accent(
            parameters,
            learner,
            original_prosody,
            spoken=list(said.values()),
            reference_sounds=reference_sounds,
        )
    else:
        # Nothing to judge: the same reason the delivery measures give.
        reason = delivered.measures["completeness"].reason
        for name in ("pronunciation", "articulation", "accent"):
            measures[name] = Measure(None, reason)
    weights = parameters.raw["overall"]["weights"]
    overall, basis = overall_score(measures, weights)
    return RoundGrade(
        {name: measures[name] for name in (*SCORED_MEASURES, "accent")},
        overall,
        basis,
        weights,
        label_words(parameters, reference_words, spoken),
        delivered.filler_count,
        delivered.echo,
        delivery.version,
        parameters.version,
    )
