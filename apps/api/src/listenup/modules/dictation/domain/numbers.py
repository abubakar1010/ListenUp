"""Numbers written as digits or as words, reduced to one comparison key.

"15", "fifteen" and "Fifteen" all become the key ``#15``, so a learner who types digits
for a spoken number (or words for a written one) is not marked wrong (Architecture 13.1).
Keys:

- ``#<value>`` for a cardinal: ``#1990``, ``#3.5``, ``#1000``.
- ``#<value>th`` for an ordinal, whatever its written suffix: "21st", "twenty-first".
- ``#<value>s`` for a plural decade: "1990s", "'90s", "the nineties".

Word numbers are read greedily from left to right. A year reading wins over two separate
numbers when the first part is 15 to 20 ("nineteen ninety" is 1990, "twenty twenty-five"
is 2025, "nineteen oh five" is 1905); other pairs stay separate, so clock times such as
"twelve thirty" keep two numbers, like "12:30". Punctuation between number words does
not stop the reading, so scores do not change when a learner adds or drops a comma.
"""

import re
from collections.abc import Sequence
from typing import Final

_UNITS: Final = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS: Final = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS: Final = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES: Final = {"thousand": 10**3, "million": 10**6, "billion": 10**9, "trillion": 10**12}
_UNIT_ORDINALS: Final = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
}
_TEEN_ORDINALS: Final = {
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
}
_TENS_ORDINALS: Final = {
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}
_SCALE_ORDINALS: Final = {
    "thousandth": 10**3,
    "millionth": 10**6,
    "billionth": 10**9,
    "trillionth": 10**12,
}
_DECADES: Final = {
    "twenties": 20,
    "thirties": 30,
    "forties": 40,
    "fifties": 50,
    "sixties": 60,
    "seventies": 70,
    "eighties": 80,
    "nineties": 90,
}
_ZEROS: Final = frozenset({"zero", "nought"})
_DIGIT_WORDS: Final = {**_UNITS, "zero": 0, "nought": 0, "oh": 0, "o": 0}
_YEAR_HUNDREDS: Final = range(15, 21)

# Words that can begin a number. "a" begins one only before "hundred" or a scale word.
NUMBER_STARTS: Final = frozenset(
    {
        *_UNITS,
        *_TEENS,
        *_TENS,
        *_UNIT_ORDINALS,
        *_TEEN_ORDINALS,
        *_TENS_ORDINALS,
        *_DECADES,
        *_ZEROS,
        "hundredth",
        *_SCALE_ORDINALS,
        "a",
    }
)

_INT = r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+"
_CARDINAL_RE: Final = re.compile(rf"(?P<int>{_INT})(?:\.(?P<frac>[0-9]+))?")
_ORDINAL_RE: Final = re.compile(rf"(?P<int>{_INT})(?:st|nd|rd|th)")
_DECADE_RE: Final = re.compile(r"(?P<int>[0-9]+)'?s")
_CLOCK_RE: Final = re.compile(r"(?P<int>[0-9]{1,2})(?P<half>am|pm)")


def number_key(value: int, fraction: str = "", suffix: str = "") -> str:
    """The comparison key for a number: ``#15``, ``#3.5``, ``#21th``, ``#1990s``."""
    return f"#{value}{'.' + fraction if fraction else ''}{suffix}"


def digit_keys(piece: str) -> list[str] | None:
    """Keys for a piece written with digits ("1,000", "3.5", "21st", "1990s", "3pm").

    Returns None when the piece is not a number in one of these forms ("mp3").
    """
    if match := _CARDINAL_RE.fullmatch(piece):
        return [number_key(int(match["int"].replace(",", "")), match["frac"] or "")]
    if match := _ORDINAL_RE.fullmatch(piece):
        return [number_key(int(match["int"].replace(",", "")), suffix="th")]
    if match := _DECADE_RE.fullmatch(piece):
        return [number_key(int(match["int"]), suffix="s")]
    if match := _CLOCK_RE.fullmatch(piece):
        return [number_key(int(match["int"])), match["half"]]
    return None


def parse_number_words(words: Sequence[str], start: int) -> tuple[str, int] | None:
    """Read a number written in words at ``words[start]``.

    Returns the number's key and how many words it used, or None when no number starts
    there. ``words`` are normalised tokens: lower case, no punctuation, hyphens split.
    """
    return _parse_year(words, start) or _parse_cardinal(words, start)


def _two_digits(words: Sequence[str], i: int) -> tuple[int, int, str] | None:
    """A 10 to 99 group for the second half of a year: value, words used, suffix."""
    if i >= len(words):
        return None
    word = words[i]
    if word in _TEENS:
        return _TEENS[word], 1, ""
    if word in _DECADES:
        return _DECADES[word], 1, "s"
    if word in _TENS:
        if i + 1 < len(words) and words[i + 1] in _UNITS:
            return _TENS[word] + _UNITS[words[i + 1]], 2, ""
        return _TENS[word], 1, ""
    return None


def _parse_year(words: Sequence[str], start: int) -> tuple[str, int] | None:
    first = words[start]
    hundreds = _TEENS.get(first, _TENS.get(first, 0))
    if hundreds not in _YEAR_HUNDREDS:
        return None
    i = start + 1
    if (
        i + 1 < len(words)
        and words[i] in ("oh", "o")
        and words[i + 1] in _UNITS
        and (i + 2 >= len(words) or words[i + 2] not in _UNITS)
    ):
        return number_key(hundreds * 100 + _UNITS[words[i + 1]]), 3
    rest = _two_digits(words, i)
    if rest is None:
        return None
    value, used, suffix = rest
    # "twenty twenty thousand" is not a year; leave it to the cardinal reading.
    after = i + used
    if after < len(words) and (words[after] == "hundred" or words[after] in _SCALES):
        return None
    return number_key(hundreds * 100 + value, suffix=suffix), 1 + used


def _parse_cardinal(words: Sequence[str], start: int) -> tuple[str, int] | None:
    n = len(words)
    i = start
    total = 0
    current = 0
    last: str | None = None  # kind of the last word read: zero, unit, teen, tens, hundred, scale
    last_scale = 10**15
    fraction = ""
    suffix = ""

    if words[i] == "a":
        if i + 1 < n and (words[i + 1] == "hundred" or words[i + 1] in _SCALES):
            current, last, i = 1, "unit", i + 1
        else:
            return None

    while i < n:
        word = words[i]
        after_group = last in (None, "hundred", "scale")
        if (
            word == "and"
            and last in ("hundred", "scale")
            and i + 1 < n
            and (
                words[i + 1] in _UNITS
                or words[i + 1] in _TEENS
                or words[i + 1] in _TENS
                or words[i + 1] in _UNIT_ORDINALS
                or words[i + 1] in _TEEN_ORDINALS
                or words[i + 1] in _TENS_ORDINALS
            )
        ):
            i += 1
            continue
        if word in _ZEROS and last is None:
            last, i = "zero", i + 1
        elif word in _UNITS and (after_group or last == "tens"):
            current += _UNITS[word]
            last, i = "unit", i + 1
        elif word in _TEENS and after_group:
            current += _TEENS[word]
            last, i = "teen", i + 1
        elif word in _TENS and after_group:
            current += _TENS[word]
            last, i = "tens", i + 1
        elif word == "hundred" and last in ("unit", "teen", "tens") and 0 < current < 100:
            current = current * 100
            last, i = "hundred", i + 1
        elif word in _SCALES and last in ("unit", "teen", "tens", "hundred"):
            scale = _SCALES[word]
            if scale >= last_scale:
                break
            total += current * scale
            current, last_scale = 0, scale
            last, i = "scale", i + 1
        elif word in _UNIT_ORDINALS and (after_group or last == "tens"):
            current += _UNIT_ORDINALS[word]
            suffix, i = "th", i + 1
            break
        elif word in _TEEN_ORDINALS and after_group:
            current += _TEEN_ORDINALS[word]
            suffix, i = "th", i + 1
            break
        elif word in _TENS_ORDINALS and after_group:
            current += _TENS_ORDINALS[word]
            suffix, i = "th", i + 1
            break
        elif word == "hundredth" and (last is None or last in ("unit", "teen", "tens")):
            current = 100 if last is None else current * 100
            suffix, i = "th", i + 1
            break
        elif word in _SCALE_ORDINALS and (
            last is None or (last in ("unit", "teen", "tens", "hundred"))
        ):
            scale = _SCALE_ORDINALS[word]
            if last is not None and scale >= last_scale:
                break
            total += (1 if last is None else current) * scale
            current = 0
            suffix, i = "th", i + 1
            break
        elif word in _DECADES and last is None:
            current = _DECADES[word]
            suffix, i = "s", i + 1
            break
        elif word == "point" and last is not None and last not in ("hundred", "scale"):
            j = i + 1
            digits = ""
            while j < n and words[j] in _DIGIT_WORDS:
                digits += str(_DIGIT_WORDS[words[j]])
                j += 1
            if not digits:
                break
            fraction, i = digits, j
            break
        else:
            break
        if last == "zero":
            # "zero" stands alone unless a decimal point follows.
            if i < n and words[i] == "point":
                continue
            break

    used = i - start
    if used == 0 or (last is None and not suffix):
        return None
    return number_key(total + current, fraction, suffix), used
