"""The product's own Dictation rules, imported from apps/api (read-only use).

B1 asks what word error rate is good enough to score Dictation (OI-2). The answer depends
on how the product compares words, so these helpers call the real tokenizer and
`score_dictation` from `listenup.modules.dictation.domain` (pure code, no database).
Run the harness with PYTHONPATH=../apps/api/src so the import resolves.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from listenup_spikes.metrics import WerResult


def available() -> bool:
    try:
        import listenup.modules.dictation.domain  # noqa: F401
    except ImportError:
        return False
    return True


def dictation_wer(reference: str, hypothesis: str) -> WerResult:
    """WER over the Dictation tokenizer's keys: numbers in digits or words, British and
    American spellings, and contractions compare equal, as they do when scoring."""
    from listenup.modules.dictation.domain.normalize import keys_equal, tokenize_text

    ref = [t.key for t in tokenize_text(reference)[1]]
    hyp = [t.key for t in tokenize_text(hypothesis)[1]]
    prev = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if keys_equal(ref[i - 1], hyp[j - 1]):
                cur.append(prev[j - 1])
                continue
            sub, dele, ins = prev[j - 1], prev[j], cur[j - 1]
            cur.append(
                min(
                    (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                    (dele[0] + 1, dele[1], dele[2] + 1, dele[3]),
                    (ins[0] + 1, ins[1], ins[2], ins[3] + 1),
                )
            )
        prev = cur
    cost, subs, dels, ins = prev[-1]
    return WerResult(cost / max(len(ref), 1), subs, dels, ins, len(ref))


@dataclass(frozen=True)
class FalseMarks:
    marks: int  # mark candidates a learner who typed every word right would get
    reference_words: int  # words in the machine transcript
    accuracy: float  # the score that learner would see, percent


def false_marks(machine_words: Sequence[tuple[str, float, float]], true_text: str) -> FalseMarks:
    """Score the true text as if a perfect learner typed it, against the machine transcript
    as the reference. Every mark candidate is a transcript error the learner would be
    blamed for (Dictation diff and marks, PRD 8.4)."""
    from listenup.modules.dictation.domain import ReferenceWord, score_dictation

    reference = [
        ReferenceWord(word, round(start * 1000), max(round(end * 1000), round(start * 1000)))
        for word, start, end in machine_words
    ]
    result = score_dictation(reference, true_text)
    return FalseMarks(len(result.mark_candidates), len(reference), float(result.accuracy))
