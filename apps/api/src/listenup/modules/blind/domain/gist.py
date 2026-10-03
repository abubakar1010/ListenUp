"""The gist the learner writes after the listen (FR-BL-4; #65; final UI D04).

A sentence ends with a full stop, a question mark or an exclamation mark followed by
a space or the end of the text, and has at least 3 words. Text after the last such
mark does not count until it is finished. The web client counts the same way
(`apps/web/src/features/blind/gist.ts`).
"""

import re

MIN_SENTENCES = 3
MAX_CHARS = 2_000
MIN_WORDS = 3

_END = re.compile(r"[.!?]+(?=\s|$)")
_WORD = re.compile(r"[^\W_]+(?:['\u2019-][^\W_]+)*")


def count_sentences(text: str) -> int:
    """How many finished sentences of at least 3 words the text has."""
    count = 0
    start = 0
    for end in _END.finditer(text):
        if len(_WORD.findall(text[start : end.start()])) >= MIN_WORDS:
            count += 1
        start = end.end()
    return count
