"""Which consents a learner still owes, and whether voice consent holds (#104, FR-SH-17)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from listenup.modules.identity.domain.consents import (
    Consent,
    ConsentKind,
    CurrentVersions,
    holds,
    outstanding,
)
from listenup.modules.identity.service import consent_versions

REPO = Path(__file__).resolve().parents[4]

NOW = datetime(2026, 10, 19, tzinfo=UTC)
CURRENT = CurrentVersions(terms="t2", privacy="p1", voice_recording="v1")


def granted(kind: ConsentKind, version: str, *, withdrawn: bool = False) -> Consent:
    return Consent(kind, version, granted_at=NOW, withdrawn_at=NOW if withdrawn else None)


def test_a_learner_with_no_consents_owes_terms_and_privacy_but_not_voice() -> None:
    assert outstanding(CURRENT, []) == [ConsentKind.TERMS, ConsentKind.PRIVACY]


def test_accepting_the_current_versions_settles_the_sign_in_prompt() -> None:
    held = [granted(ConsentKind.TERMS, "t2"), granted(ConsentKind.PRIVACY, "p1")]
    assert outstanding(CURRENT, held) == []


def test_an_older_terms_version_does_not_count_for_the_current_one() -> None:
    held = [granted(ConsentKind.TERMS, "t1"), granted(ConsentKind.PRIVACY, "p1")]
    assert outstanding(CURRENT, held) == [ConsentKind.TERMS]


def test_a_newer_unknown_version_does_not_count_either() -> None:
    # Versions are labels, not ordered numbers: only an exact match is consent.
    held = [granted(ConsentKind.TERMS, "t3"), granted(ConsentKind.PRIVACY, "p1")]
    assert outstanding(CURRENT, held) == [ConsentKind.TERMS]


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        ([], False),
        ([granted(ConsentKind.VOICE_RECORDING, "v1")], True),
        ([granted(ConsentKind.VOICE_RECORDING, "v1", withdrawn=True)], False),
        ([granted(ConsentKind.VOICE_RECORDING, "v0")], False),
        # Terms of the same version string are a different consent.
        ([granted(ConsentKind.TERMS, "v1")], False),
    ],
)
def test_voice_consent_holds_only_for_the_current_unwithdrawn_version(
    held: list[Consent], expected: bool
) -> None:
    assert holds(CURRENT, held, ConsentKind.VOICE_RECORDING) is expected


def test_only_voice_recording_consent_can_be_withdrawn() -> None:
    assert [kind for kind in ConsentKind if kind.withdrawable] == [ConsentKind.VOICE_RECORDING]


def test_current_versions_come_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from listenup.platform.config import Settings

    monkeypatch.setenv("LISTENUP_TERMS_VERSION", "2026-11")
    monkeypatch.setenv("LISTENUP_PRIVACY_VERSION", "2026-12")
    monkeypatch.setenv("LISTENUP_VOICE_CONSENT_VERSION", "voice-2")
    assert consent_versions(Settings()) == CurrentVersions("2026-11", "2026-12", "voice-2")


def test_the_default_versions_are_the_2026_1_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    from listenup.platform.config import Settings

    for name in ("TERMS", "PRIVACY", "VOICE_CONSENT"):
        monkeypatch.delenv(f"LISTENUP_{name}_VERSION", raising=False)
    # The texts in docs/legal/ (#103); a label names exactly one file there.
    versions = consent_versions(Settings(_env_file=None))  # type: ignore[call-arg]
    assert versions == CurrentVersions("terms-2026-1", "privacy-2026-1", "voice-2026-1")


def test_every_default_version_has_its_text_in_the_web_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from listenup.platform.config import Settings

    for name in ("TERMS", "PRIVACY", "VOICE_CONSENT"):
        monkeypatch.delenv(f"LISTENUP_{name}_VERSION", raising=False)
    # ADR 0051: a label names one file in docs/legal/, registered in texts.ts, or the
    # page shows an error instead of the text the learner is asked to accept.
    texts = (REPO / "apps/web/src/features/legal/texts.ts").read_text()
    versions = consent_versions(Settings(_env_file=None))  # type: ignore[call-arg]
    for label in (versions.terms, versions.privacy, versions.voice_recording):
        assert (REPO / "docs/legal" / f"{label}.md").is_file(), label
        assert f"'{label}': " in texts, label


@pytest.mark.parametrize("version", ["", "x" * 21, "has space", "v1;drop"])
def test_a_version_label_the_table_cannot_hold_is_refused(version: str) -> None:
    from pydantic import ValidationError

    from listenup.platform.config import Settings

    with pytest.raises(ValidationError):
        Settings(terms_version=version)
