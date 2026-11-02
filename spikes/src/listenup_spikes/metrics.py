"""Pure metrics used by several spikes. No model or network code here."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

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
class FillerMark:
    """One filler in a recording, in seconds. kind is "hesitation" (uh, um, er) or
    "discourse" (like, you know)."""

    start: float
    end: float
    kind: str
    text: str


# B4's fillers as a transcript spells them. "hmm" and "mm" are not B4 fillers, and the AMI
# reference leaves them out too, so they count neither way.
HESITATION_SPELLINGS = frozenset({"uh", "uhh", "um", "umm", "uhm", "er", "erm", "ah"})
MATCH_TOLERANCE_S = 0.5


def hypothesis_fillers(words: Sequence[tuple[str, float, float]]) -> list[FillerMark]:
    """B4 fillers in timed transcript words: hesitations, every "like" and "you know".
    Every "like" counts, as a filler counter that cannot tell the verb apart would."""
    tokens = [(re.sub(r"[^a-z']", "", text.lower()), start, end) for text, start, end in words]
    marks: list[FillerMark] = []
    i = 0
    while i < len(tokens):
        text, start, end = tokens[i]
        if text == "you" and i + 1 < len(tokens) and tokens[i + 1][0] == "know":
            marks.append(FillerMark(start, tokens[i + 1][2], "discourse", "you know"))
            i += 2
            continue
        if text in HESITATION_SPELLINGS:
            marks.append(FillerMark(start, end, "hesitation", text))
        elif text == "like":
            marks.append(FillerMark(start, end, "discourse", "like"))
        i += 1
    return marks


@dataclass(frozen=True)
class FillerCounts:
    hits: int
    missed: int
    extra: int

    @property
    def recall(self) -> float | None:
        return self.hits / (self.hits + self.missed) if self.hits + self.missed else None

    @property
    def precision(self) -> float | None:
        return self.hits / (self.hits + self.extra) if self.hits + self.extra else None


def match_fillers(
    reference: Sequence[FillerMark],
    hypothesis: Sequence[FillerMark],
    tolerance_s: float = MATCH_TOLERANCE_S,
) -> dict[str, FillerCounts]:
    """Pair each reference filler, in time order, with the nearest unused transcript filler
    of the same kind within tolerance_s of its ends. Spellings within a kind are
    interchangeable (AMI writes every vowel hesitation "uh")."""
    results: dict[str, FillerCounts] = {}
    for kind in ("hesitation", "discourse"):
        refs = sorted((m for m in reference if m.kind == kind), key=lambda m: m.start)
        free = sorted((m for m in hypothesis if m.kind == kind), key=lambda m: m.start)
        hits = 0
        for ref in refs:
            near = [
                h
                for h in free
                if round(h.start, 6) <= round(ref.end + tolerance_s, 6)
                and round(h.end, 6) >= round(ref.start - tolerance_s, 6)
            ]
            if near:
                middle = (ref.start + ref.end) / 2
                free.remove(min(near, key=lambda h: abs((h.start + h.end) / 2 - middle)))
                hits += 1
        results[kind] = FillerCounts(hits, len(refs) - hits, len(free))
    results["all"] = FillerCounts(
        *(sum(getattr(r, f) for r in results.values()) for f in ("hits", "missed", "extra"))
    )
    return results


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
) -> list[float]:
    """Match ordered text blocks, then measure every matched boundary without a time
    cutoff. Text context locates hand-labelled excerpts within the full passage;
    timestamps never decide which words match. Disable the popular-word heuristic
    because repeated words like 'the' are meaningful anchors in speech.

    Unmatched labels have no measurable timing error. Callers must report their count
    and must not pass an accuracy gate on incomplete coverage (see compare._row).
    """
    matcher = SequenceMatcher(
        a=[tuple(normalize_words(w)) for w, _, _ in predicted],
        b=[tuple(normalize_words(w)) for w, _, _ in labelled],
        autojunk=False,
    )
    errors: list[float] = []
    for a, b, size in matcher.get_matching_blocks():
        for offset in range(size):
            _, start, end = labelled[b + offset]
            _, pred_start, pred_end = predicted[a + offset]
            errors.extend([abs(pred_start - start) * 1000, abs(pred_end - end) * 1000])
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
