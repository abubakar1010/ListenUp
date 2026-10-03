"""Spike #20: the seven Shadow measures as pure functions over aligned words and pitch.

Prototype quality: each measure is a simple proxy whose job is to show whether the approach
can rank clear, on-time speech above mumbled, late speech (AT-17 shape). Every comparison is
against the original clip, not a fixed "native" standard (FR-SH-15).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

import numpy as np

from listenup_spikes.align import AlignedWord

MIN_WORD_SCORE = 0.35  # below this a word counts as not spoken
EXTRA_PAUSE_S = 0.3
ECHO_THRESHOLD = 0.6
MEASURES = (
    "timing",
    "pronunciation",
    "accent",
    "articulation",
    "fluency",
    "fillers",
    "completeness",
)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def completeness(learner: Sequence[AlignedWord]) -> float:
    spoken = sum(1 for w in learner if w.score >= MIN_WORD_SCORE)
    return 100 * spoken / max(len(learner), 1)


def pronunciation(learner: Sequence[AlignedWord]) -> float:
    """Proxy: mean CTC posterior of spoken words (a GOP score replaces this later)."""
    spoken = [w.score for w in learner if w.score >= MIN_WORD_SCORE]
    return 100 * (sum(spoken) / len(spoken)) if spoken else 0.0


def articulation(learner: Sequence[AlignedWord]) -> float:
    """Proxy: confidence of word endings, where dropped final sounds show up first."""
    spoken = [w.last_score for w in learner if w.score >= MIN_WORD_SCORE]
    return 100 * (sum(spoken) / len(spoken)) if spoken else 0.0


def timing(original: Sequence[AlignedWord], learner: Sequence[AlignedWord]) -> float:
    """Word-onset deviation from the original after removing the constant shadowing lag,
    combined with the speech-rate ratio."""
    pairs = [(o, s) for o, s in zip(original, learner, strict=True) if s.score >= MIN_WORD_SCORE]
    if len(pairs) < 2:
        return 0.0
    offsets = [s.start - o.start for o, s in pairs]
    lag = median(offsets)
    deviation = sum(abs(x - lag) for x in offsets) / len(offsets)
    o_span = pairs[-1][0].end - pairs[0][0].start
    s_span = pairs[-1][1].end - pairs[0][1].start
    rate_ratio = s_span / o_span if o_span > 0 else 0.0
    return 100 * _clamp(1 - deviation / 0.5) * _clamp(1 - abs(1 - rate_ratio) * 2)


def extra_pauses(original: Sequence[AlignedWord], learner: Sequence[AlignedWord]) -> int:
    count = 0
    for i in range(1, min(len(original), len(learner))):
        o_gap = original[i].start - original[i - 1].end
        s_gap = learner[i].start - learner[i - 1].end
        if s_gap > o_gap + EXTRA_PAUSE_S:
            count += 1
    return count


def fluency(original: Sequence[AlignedWord], learner: Sequence[AlignedWord]) -> float:
    allowed = max(len(learner) / 10, 1)
    return 100 * _clamp(1 - extra_pauses(original, learner) / allowed)


def fillers_score(filler_count: int | None, duration_s: float) -> float | None:
    """Fewer fillers per minute is better; 6 per minute or more scores 0."""
    if filler_count is None or duration_s <= 0:
        return None
    per_minute = filler_count / (duration_s / 60)
    return 100 * _clamp(1 - per_minute / 6)


def word_pitch(pitch_hz: np.ndarray, frame_s: float, words: Sequence[AlignedWord]) -> list[float]:
    """Median pitch (semitones re 100 Hz) of voiced frames inside each word; NaN if unvoiced."""
    out = []
    for w in words:
        frames = pitch_hz[
            int(w.start / frame_s) : max(int(w.end / frame_s), int(w.start / frame_s) + 1)
        ]
        voiced = frames[frames > 0]
        out.append(float(12 * np.log2(np.median(voiced) / 100)) if voiced.size else float("nan"))
    return out


def accent(original_pitch: Sequence[float], learner_pitch: Sequence[float]) -> float | None:
    """Experimental: correlation of the word-level intonation contour with the original's."""
    o, s = np.asarray(original_pitch), np.asarray(learner_pitch)
    mask = ~(np.isnan(o) | np.isnan(s))
    if mask.sum() < 5 or np.std(o[mask]) == 0 or np.std(s[mask]) == 0:
        return None
    r = float(np.corrcoef(o[mask], s[mask])[0, 1])
    return 100 * _clamp(r)


def echo_score(original: np.ndarray, recording: np.ndarray, rate: int = 16000) -> float:
    """Peak normalized cross-correlation of 100 Hz loudness envelopes within +/-1 s.
    A high value means the original leaked from speakers into the microphone."""

    def envelope(x: np.ndarray) -> np.ndarray:
        hop = rate // 100
        usable = len(x) - len(x) % hop
        env = np.abs(x[:usable]).reshape(-1, hop).mean(axis=1)
        return (env - env.mean()) / (env.std() or 1.0)

    a, b = envelope(original), envelope(recording)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    best = 0.0
    for lag in range(-100, 101):
        if lag >= 0:
            x, y = a[: n - lag], b[lag:]
        else:
            x, y = a[-lag:], b[: n + lag]
        if len(x) > 10:
            best = max(best, float(np.dot(x, y) / len(x)))
    return best


@dataclass(frozen=True)
class RoundMeasures:
    scores: dict[str, float | None]

    @property
    def overall(self) -> float:
        """Equal-weight mean of the measures that exist, excluding accent (D11, FR-SH-15)."""
        values = [v for k, v in self.scores.items() if k != "accent" and v is not None]
        return sum(values) / len(values) if values else 0.0
