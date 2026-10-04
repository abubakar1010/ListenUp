"""The AI gateway: providers chosen by ai.yaml, timeout and retry (ADR 0028)."""

import asyncio
from pathlib import Path

import pytest

from listenup.ai import gateway as gateway_module
from listenup.ai.config import DEFAULT_CONFIG, FAKE_CONFIG, ProviderEntry, load_config, parse_config
from listenup.ai.errors import AIConfigError, AIUnavailable, TransientProviderError
from listenup.ai.gateway import AIGateway, get_gateway
from listenup.ai.ports import Provenance, Role, Transcript
from listenup.ai.registry import DEFAULT_REGISTRY, Registry
from listenup.platform.config import get_settings

AUDIO = Path("clip.mp4")

WHISPER_YAML = """
version: 1
roles:
  transcription:
    - provider: faster-whisper
      model: base.en
"""

FAKE_YAML = """
version: 1
roles:
  transcription:
    - provider: fake
      model: fake-transcript
"""


class Scripted:
    """A transcription adapter that plays a script: an exception to raise, "slow" to
    outlast the timeout, or "ok" to answer."""

    built = 0

    def __init__(self, entry: ProviderEntry, script: list[object]) -> None:
        Scripted.built += 1
        self.entry = entry
        self.script = list(script)
        self.calls = 0
        self.loads = 0

    def load(self) -> None:
        self.loads += 1

    async def transcribe(self, audio: Path, language: str = "en") -> Transcript:
        self.calls += 1
        step = self.script.pop(0) if self.script else "ok"
        if step == "slow":
            await asyncio.sleep(10)
        if isinstance(step, BaseException):
            raise step
        return Transcript(
            provenance=Provenance(provider="scripted", model=self.entry.model, version="1"),
            language=language,
            duration_seconds=0,
            segments=(),
        )


def scripted_gateway(
    script: list[object], **entry: object
) -> tuple[AIGateway, list[Scripted], list[float]]:
    adapters: list[Scripted] = []
    sleeps: list[float] = []

    def factory(e: ProviderEntry) -> Scripted:
        adapters.append(Scripted(e, script))
        return adapters[-1]

    async def no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    config = parse_config(
        "version: 1\nroles:\n  transcription:\n    - provider: scripted\n      model: m\n"
    )
    config = config.model_copy(
        update={
            "roles": {
                Role.TRANSCRIPTION: (
                    ProviderEntry.model_validate({"provider": "scripted", "model": "m", **entry}),
                )
            }
        }
    )
    registry = Registry(transcription={"scripted": factory})
    return AIGateway(config, registry=registry, sleep=no_sleep), adapters, sleeps


def test_packaged_configurations_are_valid() -> None:
    for path in (DEFAULT_CONFIG, FAKE_CONFIG):
        AIGateway(load_config(path))  # every provider has an adapter for its role
    default = AIGateway(load_config(DEFAULT_CONFIG))
    assert default.entry(Role.TRANSCRIPTION).provider == "faster-whisper"
    assert default.entry(Role.ALIGNMENT).provider == "wav2vec2-ctc"


@pytest.mark.anyio
async def test_switching_the_provider_in_ai_yaml_changes_the_provider_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AT-22 shape: only the configuration file changes, no code."""
    config_file = tmp_path / "ai.yaml"
    monkeypatch.setenv("LISTENUP_AI_CONFIG", str(config_file))
    get_settings.cache_clear()
    try:
        config_file.write_text(WHISPER_YAML)
        get_gateway.cache_clear()
        assert get_gateway().entry(Role.TRANSCRIPTION).provider == "faster-whisper"

        config_file.write_text(FAKE_YAML)
        get_gateway.cache_clear()
        transcript = await get_gateway().transcribe(AUDIO)
        assert transcript.provenance.provider == "fake"
        assert transcript.provenance.model == "fake-transcript"
    finally:
        get_gateway.cache_clear()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_a_timeout_is_retried_with_backoff() -> None:
    gateway, adapters, sleeps = scripted_gateway(
        ["slow", "ok"], timeout_seconds=0.05, retries=2, retry_backoff_seconds=0.5
    )
    result = await gateway.transcribe(AUDIO)
    assert result.provenance.provider == "scripted"
    assert adapters[0].calls == 2
    assert sleeps == [0.5]


@pytest.mark.anyio
async def test_transient_errors_are_retried_until_attempts_run_out() -> None:
    gateway, adapters, sleeps = scripted_gateway(
        [TransientProviderError("503"), ConnectionError("reset"), TransientProviderError("503")],
        retries=2,
        retry_backoff_seconds=1,
    )
    with pytest.raises(AIUnavailable) as caught:
        await gateway.transcribe(AUDIO)
    assert caught.value.role is Role.TRANSCRIPTION
    assert adapters[0].calls == 3
    assert sleeps == [1, 2]  # doubled each time


@pytest.mark.anyio
async def test_other_errors_are_not_retried() -> None:
    gateway, adapters, _ = scripted_gateway([ValueError("cannot decode")], retries=3)
    with pytest.raises(AIUnavailable, match="cannot decode"):
        await gateway.transcribe(AUDIO)
    assert adapters[0].calls == 1


@pytest.mark.anyio
async def test_the_adapter_is_built_once_per_gateway() -> None:
    gateway, adapters, _ = scripted_gateway([])
    await gateway.transcribe(AUDIO)
    await gateway.transcribe(AUDIO)
    assert len(adapters) == 1 and adapters[0].calls == 2


@pytest.mark.anyio
async def test_preload_loads_only_providers_marked_preload() -> None:
    gateway, adapters, _ = scripted_gateway([], preload=True)
    assert await gateway.preload((Role.TRANSCRIPTION, Role.ALIGNMENT)) == ["transcription:scripted"]
    assert adapters[0].loads == 1

    lazy, lazy_adapters, _ = scripted_gateway([])
    assert await lazy.preload() == []
    assert lazy_adapters == []


@pytest.mark.anyio
async def test_a_role_without_providers_is_unavailable() -> None:
    gateway = AIGateway(load_config(DEFAULT_CONFIG))
    with pytest.raises(AIUnavailable, match="no provider configured"):
        await gateway.assess(AUDIO, "hello", AUDIO)


def test_unknown_providers_are_refused_when_the_gateway_starts() -> None:
    config = parse_config("version: 1\nroles:\n  alignment:\n    - provider: faster-whisper\n")
    with pytest.raises(AIConfigError, match="no alignment adapter named 'faster-whisper'"):
        AIGateway(config)


def test_fake_providers_are_refused_in_production() -> None:
    with pytest.raises(AIConfigError, match="not allowed in production"):
        AIGateway(load_config(FAKE_CONFIG), environment="production")
    AIGateway(load_config(DEFAULT_CONFIG), environment="production")


@pytest.mark.parametrize(
    "text",
    [
        "version: 2\nroles: {}\n",
        "version: 1\nroles:\n  vision: []\n",
        "version: 1\nroles:\n  transcription:\n    - provider: fake\n      retries: 9\n",
        "version: 1\nroles:\n  transcription:\n    - provider: fake\n      colour: red\n",
        "version: 1\nroles: [unclosed\n",
    ],
)
def test_invalid_configuration_is_refused(text: str) -> None:
    with pytest.raises(AIConfigError):
        parse_config(text)


def test_a_missing_configuration_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AIConfigError, match="cannot read"):
        load_config(tmp_path / "missing.yaml")


def test_the_default_registry_has_a_fake_for_every_port() -> None:
    for role_providers in (
        DEFAULT_REGISTRY.transcription,
        DEFAULT_REGISTRY.alignment,
        DEFAULT_REGISTRY.speech_assessment,
        DEFAULT_REGISTRY.text_ai,
    ):
        assert "fake" in role_providers
    assert gateway_module.RETRYABLE
