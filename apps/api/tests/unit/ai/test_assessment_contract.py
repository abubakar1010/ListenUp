"""Owner exception E2: synthetic assessment plumbing, never model acceptance."""

from pathlib import Path

import pytest

from listenup.ai.config import DEFAULT_CONFIG, FAKE_CONFIG, load_config
from listenup.ai.errors import AIConfigError, AIUnavailable
from listenup.ai.gateway import AIGateway, get_gateway
from listenup.ai.ports import Role, SpeechAssessment, SpeechAssessmentPort
from listenup.ai.registry import DEFAULT_REGISTRY
from listenup.ai.validation import validate_assessment
from listenup.platform.config import get_settings


@pytest.mark.anyio
async def test_at22_assessment_switch_uses_only_configuration(tmp_path, monkeypatch):
    config_file = tmp_path / "ai.yaml"
    monkeypatch.setenv("LISTENUP_AI_CONFIG", str(config_file))
    get_settings.cache_clear()
    results = []
    try:
        for provider in ("fake", "fake-assessment"):
            config_file.write_text(
                "version: 1\nroles:\n  speech_assessment:\n"
                f"    - provider: {provider}\n      model: synthetic-v1\n"
                "      local: true\n      accepted: true\n      trains_on_inputs: false\n"
            )
            get_gateway.cache_clear()
            gateway = get_gateway()
            result = await gateway.assess(Path("absent.wav"), "hello world", Path("ref.wav"))
            assert result.provenance.provider == provider
            assert result.provenance.model == "synthetic-v1"
            assert result.provenance == gateway.deployment_provenance(Role.SPEECH_ASSESSMENT)
            assert SpeechAssessment.model_validate_json(result.model_dump_json()) == result
            results.append(result)
        assert results[0].words[0].accuracy != results[1].words[0].accuracy
    finally:
        get_gateway.cache_clear()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["hello world", "hello", "", "  \n "])
async def test_second_fake_exercises_complete_assessment_schema(text):
    entry = load_config(DEFAULT_CONFIG).providers(Role.SPEECH_ASSESSMENT)[0]
    adapter = DEFAULT_REGISTRY.speech_assessment[entry.provider](entry)
    assert isinstance(adapter, SpeechAssessmentPort)
    result = await adapter.assess(Path("absent.wav"), text, Path("ref.wav"))
    assert result == await adapter.assess(Path("absent.wav"), text, Path("ref.wav"))
    assert [w.text for w in result.words] == text.split()
    assert [w.index for w in result.words] == list(range(len(text.split())))
    assert SpeechAssessment.model_validate_json(result.model_dump_json()) == result
    if text.split():
        assert result.words[0].accuracy == 0.75
        assert result.words[0].sounds[0].score == 0.75
        assert result.words[0].sounds[0].label == "synthetic"
        assert result.fillers[0].text == "um"
        assert [p.hertz for p in result.pitch[:2]] == [120.0, None]
        assert len(result.pauses) == len(text.split()) - 1
    else:
        assert result.words == result.pauses == result.fillers == result.pitch == ()
    assert validate_assessment(result, text) == result


def test_default_assessment_registration_is_disabled_and_production_safe():
    config = load_config(DEFAULT_CONFIG)
    entries = config.providers(Role.SPEECH_ASSESSMENT)
    assert len(entries) == 1
    assert entries[0].provider == "fake-assessment"
    assert not entries[0].enabled
    AIGateway(config, environment="production")


@pytest.mark.parametrize("provider", ["fake", "fake-assessment"])
def test_enabled_assessment_fakes_are_refused_in_production(provider):
    config = load_config(FAKE_CONFIG)
    entry = config.providers(Role.SPEECH_ASSESSMENT)[0].model_copy(update={"provider": provider})
    config = config.model_copy(update={"roles": {Role.SPEECH_ASSESSMENT: (entry,)}})
    with pytest.raises(AIConfigError, match="not allowed in production"):
        AIGateway(config, environment="production")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [{"enabled": False}, {"accepted": False}, {"trains_on_inputs": True}],
)
async def test_ineligible_second_fake_is_not_called(change, fake_accounting):
    config = load_config(FAKE_CONFIG)
    entry = (
        load_config(DEFAULT_CONFIG)
        .providers(Role.SPEECH_ASSESSMENT)[0]
        .model_copy(update={"enabled": True, **change})
    )
    config = config.model_copy(update={"roles": {Role.SPEECH_ASSESSMENT: (entry,)}})
    with pytest.raises(AIUnavailable):
        await AIGateway(config).assess(Path("absent.wav"), "hello", Path("ref.wav"))
    assert [(row["provider"], row["outcome"]) for row in fake_accounting.calls] == [
        ("fake-assessment", "ineligible")
    ]


@pytest.mark.anyio
async def test_second_fake_is_a_gateway_fallback_when_first_is_unavailable(fake_accounting):
    fake_accounting.exhausted.add("fake")
    config = load_config(FAKE_CONFIG)
    second = (
        load_config(DEFAULT_CONFIG)
        .providers(Role.SPEECH_ASSESSMENT)[0]
        .model_copy(update={"enabled": True})
    )
    config = config.model_copy(
        update={
            "roles": {Role.SPEECH_ASSESSMENT: (*config.providers(Role.SPEECH_ASSESSMENT), second)}
        }
    )
    result = await AIGateway(config).assess(Path("absent.wav"), "hello world", Path("ref.wav"))
    assert result.provenance.provider == "fake-assessment"
    assert result.words[0].sounds[0].score == 0.75
    assert [row["outcome"] for row in fake_accounting.calls] == ["quota", "ok"]
