"""What a takedown names and what the learner reads about it (#105, NFR-USE-3, ADR 0098).

Pure rules, no I/O. A takedown names a source without any learner id: an uploaded
file by its SHA-256 (`upload:<sha256>`), so the same file is refused for every learner,
although each learner's media object carries their own id in its fingerprint
(`upload:<user id>:<sha256>`, ADR 0020). The YouTube half (#38) adds `youtube:<id>`.
"""

import re
from typing import Literal

Grounds = Literal["copyright", "other_rights", "unlawful"]

_UPLOAD = re.compile(r"upload:([0-9a-fA-F]{64})")

# Said to every learner whose clip was removed, after the reason (NFR-USE-3).
_KEPT = " It can't be played or added to ListenUp again. Your sessions, marks and cards are kept."

REMOVAL_MESSAGES: dict[str, str] = {
    "copyright": "We removed this clip because its copyright owner asked us to." + _KEPT,
    "other_rights": (
        "We removed this clip because it breaks someone else's rights, such as their "
        "privacy." + _KEPT
    ),
    "unlawful": "We removed this clip because the law does not allow us to keep it." + _KEPT,
}

# The refusal when a learner adds a file that was taken down (stored as `error_code`).
REFUSED_CODE = "source_taken_down"
REFUSED_MESSAGE = (
    "This file was removed from ListenUp after a rights complaint, so it can't be added "
    "again. Choose another file."
)

UNAVAILABLE_MESSAGE = "This clip was removed from ListenUp, so it can no longer be played."


def source_fingerprint(text: str) -> str | None:
    """The takedown fingerprint in its stored form (lower-case hex), or None."""
    match = _UPLOAD.fullmatch(text.strip())
    return f"upload:{match.group(1).lower()}" if match else None


def upload_fingerprint(sha256: str) -> str:
    """The takedown fingerprint of an uploaded file with this hash."""
    return f"upload:{sha256.lower()}"


def removal_message(grounds: str) -> str:
    """Why the clip was removed, as the learner reads it."""
    return REMOVAL_MESSAGES.get(grounds, REMOVAL_MESSAGES["other_rights"])
