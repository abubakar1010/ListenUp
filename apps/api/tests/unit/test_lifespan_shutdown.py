"""Telemetry is flushed on shutdown even when an earlier shutdown step fails."""

import pytest
from fastapi.testclient import TestClient

from listenup import main
from listenup.platform.config import Settings


class FailingListener:
    def __init__(self, *_: object) -> None: ...

    def start(self) -> None: ...

    async def stop(self) -> None:
        raise RuntimeError("listener would not stop")


def test_shutdown_flushes_telemetry_when_a_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    flushed: list[bool] = []
    monkeypatch.setattr(main, "EventListener", FailingListener)
    monkeypatch.setattr(main, "shutdown_telemetry", lambda: flushed.append(True))

    with (
        pytest.raises(RuntimeError, match="would not stop"),
        TestClient(main.create_app(Settings())),
    ):
        pass

    assert flushed == [True]
