"""Turn task input into chat messages: fit it to the token budget, then wrap it as data.

- `fit` runs before the gateway (ADR 0043). Reference text a prompt file marks `trim` is
  shortened at a word boundary to fit; learner text is never changed, so an over-long
  learner text is refused instead (ADR 0041). Sizes use the gateway's own measure: the UTF-8
  bytes of the JSON input, one byte per token, which over-counts and so stays safe.
- `render_messages` puts the instructions in the system message and every input field in
  one JSON block between per-call random markers that the data cannot contain, and the
  instructions say to treat the block as data (Architecture 7.3, FR-BL-12). Only the
  fields the prompt file lists may be sent, each shaped by the task's input model in
  `tasks.py` down to nested values, so no identifier can ride along (FR-BL-13).
"""

import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from listenup.ai.prompt_files import DELIMITER, PromptSpec
from listenup.ai.tasks import TASK_INPUTS

TRUNCATED = " [truncated]"
NOTHING_KEPT = "[truncated]"
_NONCE_TRIES = 5


class InputTooLarge(ValueError):
    """The input does not fit the token budget even after trimming reference text."""


@dataclass(frozen=True)
class Fitted:
    input: dict[str, Any]
    trimmed: tuple[str, ...]  # names of the fields that were shortened


def serialized_size(input: Mapping[str, Any]) -> int:
    return len(json.dumps(input, ensure_ascii=False).encode())


def _check_fields(spec: PromptSpec, input: Mapping[str, Any]) -> None:
    if set(input) != spec.field_names:
        raise ValueError("input fields do not match the prompt file")
    try:
        TASK_INPUTS[spec.task].model_validate(dict(input))
    except ValidationError:
        # The validation message would quote the input, which can be learner text.
        raise ValueError("input does not match the task's input model") from None


def _shorten(text: str, keep: int) -> str:
    """The first `keep` characters, cut back to a word boundary, with the marker."""
    prefix = text[:keep]
    if keep < len(text) and not text[keep].isspace():
        cut = re.search(r"\s\S*$", prefix)
        if cut and prefix[: cut.start()].strip():
            prefix = prefix[: cut.start()]
    prefix = prefix.rstrip()
    return prefix + TRUNCATED if prefix else NOTHING_KEPT


def fit(spec: PromptSpec, input: Mapping[str, Any], budget_bytes: int) -> Fitted:
    """`input` shortened to at most `budget_bytes`, or `InputTooLarge`."""
    _check_fields(spec, input)
    data = dict(input)
    trimmed: list[str] = []
    for field in spec.input_fields:
        if serialized_size(data) <= budget_bytes:
            break
        text = data[field.name]
        if not field.trim or not isinstance(text, str):
            continue
        low, high = 0, len(text)  # the most characters kept that still fits
        while low < high:
            middle = (low + high + 1) // 2
            if serialized_size({**data, field.name: _shorten(text, middle)}) <= budget_bytes:
                low = middle
            else:
                high = middle - 1
        data[field.name] = _shorten(text, low)
        trimmed.append(field.name)
    if serialized_size(data) > budget_bytes or any(data[name] == NOTHING_KEPT for name in trimmed):
        raise InputTooLarge("input exceeds the token budget")
    return Fitted(data, tuple(trimmed))


def render_messages(
    spec: PromptSpec,
    input: Mapping[str, Any],
    *,
    new_nonce: Callable[[], str] = lambda: secrets.token_hex(8),
) -> list[dict[str, str]]:
    _check_fields(spec, input)
    block = json.dumps(dict(input), ensure_ascii=False)
    for _ in range(_NONCE_TRIES):
        nonce = new_nonce()
        if f"<<<DATA {nonce}>>>" not in block and f"<<<END DATA {nonce}>>>" not in block:
            break
    else:
        raise ValueError("cannot find a data delimiter absent from the input")
    start, end = f"<<<DATA {nonce}>>>", f"<<<END DATA {nonce}>>>"
    return [
        {"role": "system", "content": spec.body.replace(DELIMITER, f"{start} and {end}")},
        {"role": "user", "content": f"{start}\n{block}\n{end}"},
    ]
