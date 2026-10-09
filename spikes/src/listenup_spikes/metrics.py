"""Pure metrics used by several spikes. No model or network code here."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

FILLERS = ("um", "uh", "er", "erm", "hmm", "like", "you know")
_CONTRACTIONS = {
    "could've": "could have",
    "would've": "would have",
    "should've": "should have",
    "can't": "cannot",
    "won't": "will not",
    "it's": "it is",
    "i'm": "i am",
    "don't": "do not",
    "doesn't": "does not",
    "isn't": "is not",
    "that's": "that is",
    "you're": "you are",
    "they're": "they are",
    "we're": "we are",
    "i've": "i have",
}


def normalize_words(text: str) -> list[str]:
    """Lower-case, unify apostrophes, expand common contractions, drop punctuation."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    words = re.findall(r"[a-z0-9']+", text)
    out: list[str] = []
    for word in words:
        out.extend(_CONTRACTIONS.get(word, word).split())
    return [w.strip("'") for w in out if w.strip("'")]


@dataclass(frozen=True)
class WerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int


def word_error_rate(reference: str, hypothesis: str) -> WerResult:
    """Word error rate by Levenshtein alignment over normalized words."""
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    # dp[i][j] = (cost, subs, dels, ins) for ref[:i] vs hyp[:j]
    prev = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur.append(prev[j - 1])
                continue
            sub, dele, ins = prev[j - 1], prev[j], cur[j - 1]
            best = min(
                (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                (dele[0] + 1, dele[1], dele[2] + 1, dele[3]),
                (ins[0] + 1, ins[1], ins[2], ins[3] + 1),
            )
            cur.append(best)
        prev = cur
    cost, subs, dels, ins = prev[-1]
    return WerResult(cost / max(len(ref), 1), subs, dels, ins, len(ref))


def count_fillers(text: str) -> int:
    words = normalize_words(text)
    joined = " " + " ".join(words) + " "
    count = sum(joined.count(f" {f} ") for f in FILLERS if " " in f)
    count += sum(1 for w in words if w in FILLERS)
    return count


@dataclass(frozen=True)
class RecallPrecision:
    recall: float
    precision: float


def filler_recall_precision(
    true_counts: Sequence[int], found_counts: Sequence[int]
) -> RecallPrecision:
    """Aggregate recall/precision of filler counts across recordings (count-level match)."""
    matched = sum(min(t, f) for t, f in zip(true_counts, found_counts, strict=True))
    total_true, total_found = sum(true_counts), sum(found_counts)
    return RecallPrecision(
        recall=matched / total_true if total_true else 1.0,
        precision=matched / total_found if total_found else 1.0,
    )


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..100)."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, round(pct / 100 * len(ordered) + 0.4999))
    return ordered[min(rank, len(ordered)) - 1]


def mean_boundary_error_ms(
    predicted: Sequence[tuple[str, float, float]], labelled: Sequence[tuple[str, float, float]]
) -> float:
    """Mean absolute error (ms) of word start and end times, matching words in order."""
    errors: list[float] = []
    j = 0
    for word, start, end in labelled:
        while j < len(predicted) and normalize_words(predicted[j][0]) != normalize_words(word):
            j += 1
        if j == len(predicted):
            break
        errors.extend([abs(predicted[j][1] - start) * 1000, abs(predicted[j][2] - end) * 1000])
        j += 1
    if not errors:
        raise ValueError("no matching words")
    return sum(errors) / len(errors)


def boundary_errors_ms(
    predicted: Sequence[tuple[str, float, float]],
    labelled: Sequence[tuple[str, float, float]],
    max_shift_s: float = 1.0,
) -> list[float]:
    """Absolute start and end errors (ms) for each labelled word that a predicted word
    matches: the same normalised text, starting within max_shift_s, nearest first, and
    in order. Labels may cover only part of the predicted span (a hand-labelled window),
    so matching is by time as well as text; unmatched labelled words are skipped."""
    errors: list[float] = []
    j = 0
    for word, start, end in labelled:
        key = normalize_words(word)
        best = None
        k = j
        while k < len(predicted) and predicted[k][1] <= start + max_shift_s:
            shift = abs(predicted[k][1] - start)
            if (
                shift <= max_shift_s
                and normalize_words(predicted[k][0]) == key
                and (best is None or shift < abs(predicted[best][1] - start))
            ):
                best = k
            k += 1
        if best is None:
            continue
        errors.extend(
            [abs(predicted[best][1] - start) * 1000, abs(predicted[best][2] - end) * 1000]
        )
        j = best + 1
    return errors


@dataclass(frozen=True)
class Spread:
    count: int
    mean: float
    median: float
    p90: float
    share_within_50ms: float  # 0..1
    share_within_100ms: float


def spread(values: Sequence[float]) -> Spread:
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return Spread(
        count=len(ordered),
        mean=sum(ordered) / len(ordered),
        median=median,
        p90=percentile(ordered, 90),
        share_within_50ms=sum(v <= 50 for v in ordered) / len(ordered),
        share_within_100ms=sum(v <= 100 for v in ordered) / len(ordered),
    )
