"""Weighted edit-distance alignment of typed tokens to reference tokens (ADR 0008).

The aligner returns one operation per reference token, plus one per extra typed token,
in text order. Costs are integers so equal costs compare exactly, and ties are broken
in a fixed order (substitute, then missing, then extra, then split, then join), so the
same input always gives the same alignment.

Long passages: a full table would be about 6.5 million cells for a 15-minute passage
(FR-DI-1). Instead the aligner first takes the common start and end, then anchors on
tokens that occur exactly once on both sides and are in the same order (patience
diff), and fills the gaps between anchors with the weighted table. A gap that is still
larger than ``MAX_TABLE_CELLS`` with no unique anchors is split on its longest common
runs (``difflib``); a gap with nothing in common is paired word by word.
"""

import difflib
from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final

from listenup.modules.dictation.domain.normalize import Token, keys_equal

# Costs, in tenths of an edit.
MISSING_COST: Final = 10
EXTRA_COST: Final = 10
SLIP_COST: Final = 4
JOIN_SPLIT_COST: Final = 5  # "alot" for "a lot", "every one" for "everyone"
WRONG_BASE_COST: Final = 11  # plus up to 8 by how different the letters are; below 20
WRONG_SPREAD: Final = 8

MAX_TABLE_CELLS: Final = 10_000


class OpKind(StrEnum):
    MATCH = "match"
    SLIP = "slip"
    WRONG = "wrong"
    MISSING = "missing"
    EXTRA = "extra"


@dataclass(frozen=True, slots=True)
class AlignOp:
    """One step of the alignment: reference token indexes and typed token indexes.

    MATCH, SLIP and WRONG pair tokens (a SLIP may pair one with two, for joined or
    split words); MISSING has only reference tokens; EXTRA has only typed tokens.
    """

    kind: OpKind
    ref: tuple[int, ...]
    typed: tuple[int, ...]


def slip_allowance(length: int) -> int:
    """How many letter edits a word of this length may have and still be a spelling slip.

    "A substitution within one or two letters" (Architecture 13.1), scaled by length so
    that short words such as "in" and "on" or "he" and "she" count as different words.
    Words of three letters or fewer allow no edit except a swapped or doubled letter
    ("teh" for "the", "dogg" for "dog"); see ``is_spelling_slip``.
    """
    if length <= 3:
        return 0
    if length == 4:
        return 1
    return 2


def is_spelling_slip(ref: Token, typed: Token) -> bool:
    """Whether ``typed`` is a misspelling of ``ref`` rather than a different word."""
    if ref.is_number or typed.is_number or ref.key.startswith("'") or typed.key.startswith("'"):
        return False
    a, b = ref.key, typed.key
    if a == b:
        return False
    allowance = slip_allowance(len(a))
    if allowance == 0:
        return _swapped_or_doubled(a, b)
    return abs(len(a) - len(b)) <= allowance and letter_distance(a, b) <= allowance


def _swapped_or_doubled(a: str, b: str) -> bool:
    if len(a) == len(b):
        diffs = [k for k in range(len(a)) if a[k] != b[k]]
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(longer) != len(shorter) + 1:
        return False
    return any(
        longer[k] == longer[k - 1] and longer[:k] + longer[k + 1 :] == shorter
        for k in range(1, len(longer))
    )


@lru_cache(maxsize=65_536)
def letter_distance(a: str, b: str) -> int:
    """Edit distance with adjacent transpositions (optimal string alignment)."""
    if a == b:
        return 0
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            substitution = previous[j - 1] + (a[i - 1] != b[j - 1])
            current[j] = min(previous[j] + 1, current[j - 1] + 1, substitution)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], previous2[j - 2] + 1)
        previous2, previous = previous, current
    return previous[len(b)]


def _substitution(ref: Token, typed: Token) -> tuple[int, OpKind]:
    if keys_equal(ref.key, typed.key):
        return 0, OpKind.MATCH
    if is_spelling_slip(ref, typed):
        return SLIP_COST, OpKind.SLIP
    longest = max(len(ref.key), len(typed.key))
    spread = (WRONG_SPREAD * min(letter_distance(ref.key, typed.key), longest)) // longest
    return WRONG_BASE_COST + spread, OpKind.WRONG


def _joinable(parts: Sequence[Token], whole: Token) -> bool:
    return "".join(part.surface for part in parts) == whole.surface


def align(ref: Sequence[Token], typed: Sequence[Token]) -> list[AlignOp]:
    """Align typed tokens to reference tokens; deterministic, in text order."""
    out: list[AlignOp] = []
    _align_range(ref, typed, 0, len(ref), 0, len(typed), out)
    return out


def _align_range(
    ref: Sequence[Token],
    typed: Sequence[Token],
    a0: int,
    a1: int,
    b0: int,
    b1: int,
    out: list[AlignOp],
) -> None:
    while a0 < a1 and b0 < b1 and ref[a0].key == typed[b0].key:
        out.append(AlignOp(OpKind.MATCH, (a0,), (b0,)))
        a0, b0 = a0 + 1, b0 + 1
    tail: list[AlignOp] = []
    while a1 > a0 and b1 > b0 and ref[a1 - 1].key == typed[b1 - 1].key:
        a1, b1 = a1 - 1, b1 - 1
        tail.append(AlignOp(OpKind.MATCH, (a1,), (b1,)))

    if a0 == a1 or b0 == b1 or (a1 - a0) * (b1 - b0) <= MAX_TABLE_CELLS:
        out.extend(_table(ref, typed, a0, a1, b0, b1))
    else:
        anchors = _unique_anchors(ref, typed, a0, a1, b0, b1) or _common_runs(
            ref, typed, a0, a1, b0, b1
        )
        if anchors:
            i, j = a0, b0
            for ai, bj in anchors:
                _align_range(ref, typed, i, ai, j, bj, out)
                out.append(AlignOp(OpKind.MATCH, (ai,), (bj,)))
                i, j = ai + 1, bj + 1
            _align_range(ref, typed, i, a1, j, b1, out)
        else:
            out.extend(_pairwise(ref, typed, a0, a1, b0, b1))
    out.extend(reversed(tail))


def _unique_anchors(
    ref: Sequence[Token], typed: Sequence[Token], a0: int, a1: int, b0: int, b1: int
) -> list[tuple[int, int]]:
    """Tokens found exactly once on each side, kept in the longest common order."""
    ref_counts = Counter(ref[i].key for i in range(a0, a1))
    typed_counts = Counter(typed[j].key for j in range(b0, b1))
    typed_at = {typed[j].key: j for j in range(b0, b1) if typed_counts[typed[j].key] == 1}
    pairs = [
        (i, typed_at[ref[i].key])
        for i in range(a0, a1)
        if ref_counts[ref[i].key] == 1 and ref[i].key in typed_at
    ]
    return _longest_increasing(pairs)


def _longest_increasing(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Longest subsequence of ``pairs`` (sorted by first item) increasing in the second."""
    tails: list[int] = []  # typed index ending the best run of each length
    tail_at: list[int] = []  # position in pairs of that run's last pair
    parent: list[int] = [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        length = bisect_left(tails, j)
        if length == len(tails):
            tails.append(j)
            tail_at.append(k)
        else:
            tails[length] = j
            tail_at[length] = k
        parent[k] = tail_at[length - 1] if length > 0 else -1
    result: list[tuple[int, int]] = []
    k = tail_at[-1] if tail_at else -1
    while k >= 0:
        result.append(pairs[k])
        k = parent[k]
    result.reverse()
    return result


def _common_runs(
    ref: Sequence[Token], typed: Sequence[Token], a0: int, a1: int, b0: int, b1: int
) -> list[tuple[int, int]]:
    matcher = difflib.SequenceMatcher(
        None,
        [ref[i].key for i in range(a0, a1)],
        [typed[j].key for j in range(b0, b1)],
        autojunk=False,
    )
    return [
        (a0 + block.a + k, b0 + block.b + k)
        for block in matcher.get_matching_blocks()
        for k in range(block.size)
    ]


def _pairwise(
    ref: Sequence[Token], typed: Sequence[Token], a0: int, a1: int, b0: int, b1: int
) -> list[AlignOp]:
    """Fallback for a large gap with nothing in common: pair tokens in order."""
    ops: list[AlignOp] = []
    paired = min(a1 - a0, b1 - b0)
    for k in range(paired):
        _, kind = _substitution(ref[a0 + k], typed[b0 + k])
        ops.append(AlignOp(kind, (a0 + k,), (b0 + k,)))
    ops.extend(AlignOp(OpKind.MISSING, (i,), ()) for i in range(a0 + paired, a1))
    ops.extend(AlignOp(OpKind.EXTRA, (), (j,)) for j in range(b0 + paired, b1))
    return ops


# Back-pointer codes for the table.
_SUBSTITUTE, _MISSING, _EXTRA, _SPLIT, _JOIN = 1, 2, 3, 4, 5


def _table(
    ref: Sequence[Token], typed: Sequence[Token], a0: int, a1: int, b0: int, b1: int
) -> list[AlignOp]:
    """Weighted edit distance over one gap, with a fixed tie-break order."""
    n, m = a1 - a0, b1 - b0
    a = ref[a0:a1]
    b = typed[b0:b1]
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    kinds: dict[tuple[int, int], OpKind] = {}
    for j in range(1, m + 1):
        cost[0][j] = j * EXTRA_COST
        back[0][j] = _EXTRA
    for i in range(1, n + 1):
        cost[i][0] = i * MISSING_COST
        back[i][0] = _MISSING
        row, previous = cost[i], cost[i - 1]
        back_row = back[i]
        ref_token = a[i - 1]
        for j in range(1, m + 1):
            substitution, kind = _substitution(ref_token, b[j - 1])
            best, code = previous[j - 1] + substitution, _SUBSTITUTE
            if (c := previous[j] + MISSING_COST) < best:
                best, code = c, _MISSING
            if (c := row[j - 1] + EXTRA_COST) < best:
                best, code = c, _EXTRA
            if (
                j >= 2
                and (c := previous[j - 2] + JOIN_SPLIT_COST) < best
                and _joinable(b[j - 2 : j], ref_token)
            ):
                best, code = c, _SPLIT
            if (
                i >= 2
                and (c := cost[i - 2][j - 1] + JOIN_SPLIT_COST) < best
                and _joinable(a[i - 2 : i], b[j - 1])
            ):
                best, code = c, _JOIN
            row[j] = best
            back_row[j] = code
            if code == _SUBSTITUTE:
                kinds[(i, j)] = kind

    ops: list[AlignOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        code = back[i][j]
        if code == _SUBSTITUTE:
            ops.append(AlignOp(kinds[(i, j)], (a0 + i - 1,), (b0 + j - 1,)))
            i, j = i - 1, j - 1
        elif code == _MISSING:
            ops.append(AlignOp(OpKind.MISSING, (a0 + i - 1,), ()))
            i -= 1
        elif code == _EXTRA:
            ops.append(AlignOp(OpKind.EXTRA, (), (b0 + j - 1,)))
            j -= 1
        elif code == _SPLIT:
            ops.append(AlignOp(OpKind.SLIP, (a0 + i - 1,), (b0 + j - 2, b0 + j - 1)))
            i, j = i - 1, j - 2
        else:
            ops.append(AlignOp(OpKind.SLIP, (a0 + i - 2, a0 + i - 1), (b0 + j - 1,)))
            i, j = i - 2, j - 1
    ops.reverse()
    return ops
