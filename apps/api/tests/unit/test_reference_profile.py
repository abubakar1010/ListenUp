"""Packed original evidence, never learner scores (#76)."""

import pytest

from listenup.ai.ports import AlignedWord, Alignment, Provenance


def aligned():
    return Alignment(
        provenance=Provenance(provider="test", model="word", version="v1"),
        unit_kind="character",
        words=(AlignedWord(index=1, text="hello", start=0.1, end=0.5, confidence=0.9, units=()),),
    )


def test_profile_pack_preserves_missing_words_and_absolute_times():
    from listenup.modules.transcript.profile_packing import pack_alignment

    packed = pack_alignment(aligned(), ["123", "hello"], (5000, 6000))
    assert packed == dict(
        word_indices=[1], word_start_ms=[5100], word_end_ms=[5500], word_confidence=[900]
    )


@pytest.mark.parametrize("change", [{"index": 2}, {"text": "wrong"}, {"end": 2}, {"end": 0.1}])
def test_profile_pack_rejects_invalid_evidence(change):
    from listenup.modules.transcript.profile_packing import pack_alignment

    bad = aligned().model_copy(update={"words": (aligned().words[0].model_copy(update=change),)})
    with pytest.raises(ValueError):
        pack_alignment(bad, ["123", "hello"], (5000, 6000))


def test_processing_fingerprint_changes_with_versions_and_settings():
    from listenup.modules.transcript.profile_packing import fingerprint

    first = fingerprint({"version": "v1", "window_seconds": 30})
    assert len(first) == 64
    assert first == fingerprint({"window_seconds": 30, "version": "v1"})
    assert first != fingerprint({"version": "v2", "window_seconds": 30})
    assert first != fingerprint({"version": "v1", "window_seconds": 20})


def test_gateway_trusted_deployment_identity():
    from listenup.ai.config import AIConfig, ProviderEntry
    from listenup.ai.gateway import AIGateway
    from listenup.ai.ports import Role

    gateway = AIGateway(
        AIConfig(
            version=1,
            roles={Role.ALIGNMENT: [ProviderEntry(provider="fake", model="fake-alignment")]},
        )
    )
    assert gateway.deployment_provenance(Role.ALIGNMENT).model_dump() == {
        "provider": "fake",
        "model": "fake-alignment",
        "version": "1",
    }
