"""Compact original word evidence and stable recipe identities (#76, ADR 0050)."""

import hashlib
import json
from typing import Any

from listenup.ai.ports import Alignment


def fingerprint(recipe: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def pack_alignment(
    result: Alignment, words: list[str], span: tuple[int, int]
) -> dict[str, list[int]]:
    packed: dict[str, list[int]] = dict(
        word_indices=[], word_start_ms=[], word_end_ms=[], word_confidence=[]
    )
    previous = -1
    previous_end = span[0]
    for word in result.words:
        start, end = span[0] + round(word.start * 1000), span[0] + round(word.end * 1000)
        if not (
            previous < word.index < len(words)
            and word.text == words[word.index]
            and previous_end <= start < end <= span[1]
        ):
            raise ValueError("Invalid aligned word evidence")
        packed["word_indices"].append(word.index)
        packed["word_start_ms"].append(start)
        packed["word_end_ms"].append(end)
        packed["word_confidence"].append(round(word.confidence * 1000))
        previous, previous_end = word.index, end
    return packed
