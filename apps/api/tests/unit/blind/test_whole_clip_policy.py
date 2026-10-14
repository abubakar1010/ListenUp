"""Whole-clip access follows the server's unfinished-listen state (ADR 0033)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest

from listenup.modules.blind import repository, service
from listenup.modules.blind.domain import Listen
from listenup.modules.practice import service as practice
from listenup.modules.practice.service import Step
from listenup.platform.errors import ProblemError

T0 = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("row_missing", [False, True])
def test_an_active_unfinished_listen_blocks_whole_clip(
    monkeypatch: pytest.MonkeyPatch, row_missing: bool
) -> None:
    learner, content_id, attempt_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = object()
    monkeypatch.setattr(
        practice,
        "active_attempts_for_content",
        AsyncMock(return_value=[SimpleNamespace(id=attempt_id)]),
    )
    row = None if row_missing else SimpleNamespace(listen=Listen.start(0, 10_000, T0))
    monkeypatch.setattr(repository, "get", AsyncMock(return_value=row))

    with pytest.raises(ProblemError) as refused:
        anyio.run(
            service.require_whole_clip_available,
            db,
            learner,
            [content_id],
            T0 + timedelta(seconds=2),
        )

    assert (refused.value.status, refused.value.code) == (409, "blind_in_progress")
    practice.active_attempts_for_content.assert_awaited_once_with(  # type: ignore[attr-defined]
        db, learner, content_id, Step.BLIND
    )


def test_a_server_completed_listen_does_not_block_whole_clip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learner, content_id, attempt_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    listen = replace(Listen.start(0, 10_000, T0), last_position_ms=9_500)
    monkeypatch.setattr(
        practice,
        "active_attempts_for_content",
        AsyncMock(return_value=[SimpleNamespace(id=attempt_id)]),
    )
    monkeypatch.setattr(repository, "get", AsyncMock(return_value=SimpleNamespace(listen=listen)))

    anyio.run(
        service.require_whole_clip_available,
        object(),
        learner,
        [content_id],
        T0 + timedelta(seconds=10),
    )


def test_a_voided_attempt_does_not_block_whole_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    learner, content_id = uuid.uuid4(), uuid.uuid4()
    active = AsyncMock(return_value=[])
    monkeypatch.setattr(practice, "active_attempts_for_content", active)

    anyio.run(service.require_whole_clip_available, object(), learner, [content_id], T0)

    active.assert_awaited_once()
