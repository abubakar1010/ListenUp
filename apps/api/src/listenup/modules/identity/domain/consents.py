"""Versioned consents: which ones a learner holds and which they still owe (#104, FR-SH-17).

A consent counts only for the exact version that is current now. Versions are labels
chosen with the policy text (#103), not ordered numbers, so a newer or older label is
simply a different version. Terms and privacy are owed by every account and asked for
again when their version changes; voice recording is asked for before the first Shadow
round (#78) and is the only consent a learner can withdraw on its own (withdrawing
terms or privacy means deleting the account).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ConsentKind(StrEnum):
    TERMS = "terms"
    PRIVACY = "privacy"
    VOICE_RECORDING = "voice_recording"

    @property
    def withdrawable(self) -> bool:
        return self is ConsentKind.VOICE_RECORDING


# Accepted at sign-up and asked for again on sign-in when their version changes.
SIGN_IN_KINDS = (ConsentKind.TERMS, ConsentKind.PRIVACY)


@dataclass(frozen=True)
class CurrentVersions:
    terms: str
    privacy: str
    voice_recording: str

    def of(self, kind: ConsentKind) -> str:
        version: str = getattr(self, kind.value)
        return version


@dataclass(frozen=True)
class Consent:
    kind: ConsentKind
    version: str
    granted_at: datetime
    withdrawn_at: datetime | None


def holds(current: CurrentVersions, held: Iterable[Consent], kind: ConsentKind) -> bool:
    """True when the learner granted the current version of `kind` and did not withdraw it."""
    version = current.of(kind)
    return any(c.kind is kind and c.version == version and c.withdrawn_at is None for c in held)


def outstanding(current: CurrentVersions, held: Iterable[Consent]) -> list[ConsentKind]:
    """The sign-in consents whose current version the learner has not accepted yet."""
    held = list(held)
    return [kind for kind in SIGN_IN_KINDS if not holds(current, held, kind)]
