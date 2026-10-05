"""The media worker loads its speech models before taking work (System Design 5.2)."""

import pytest

from listenup import worker
from listenup.ai.ports import Role


class Gateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.roles: tuple[Role, ...] | None = None

    async def preload(self, roles: tuple[Role, ...]) -> list[str]:
        self.roles = roles
        if self.error:
            raise self.error
        return [f"{role.value}:x" for role in roles]


@pytest.mark.anyio
async def test_media_pool_preloads_transcription_and_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = Gateway()
    monkeypatch.setattr(worker, "get_gateway", lambda: gateway)
    await worker.load_models("default")
    assert gateway.roles is None
    await worker.load_models("media")
    assert gateway.roles == (Role.TRANSCRIPTION, Role.ALIGNMENT)


@pytest.mark.anyio
async def test_missing_speech_libraries_stop_the_media_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = Gateway(ModuleNotFoundError("No module named 'faster_whisper'"))
    monkeypatch.setattr(worker, "get_gateway", lambda: gateway)
    with pytest.raises(SystemExit, match="install the speech extra"):
        await worker.load_models("media")
