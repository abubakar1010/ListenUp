"""Ownership is checked before Blind whole-clip policy (ADR 0033, NFR-SEC-2)."""

import uuid
from unittest.mock import AsyncMock

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import repository, service
from listenup.platform.errors import ProblemError


def test_media_without_an_owned_content_item_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock(spec=AsyncSession)
    learner, media_id = uuid.uuid4(), uuid.uuid4()
    lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "learner_content_ids_for_media", lookup)

    with pytest.raises(ProblemError) as refused:
        anyio.run(service.learner_content_ids_for_media, db, learner, media_id)

    assert (refused.value.status, refused.value.code) == (404, "media_not_found")
    lookup.assert_awaited_once_with(db, learner, media_id)


def test_all_owned_content_items_are_returned_for_the_blind_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    learner, media_id = uuid.uuid4(), uuid.uuid4()
    content_ids = [uuid.uuid4(), uuid.uuid4()]
    lookup = AsyncMock(return_value=content_ids)
    monkeypatch.setattr(repository, "learner_content_ids_for_media", lookup)

    owned = anyio.run(service.learner_content_ids_for_media, db, learner, media_id)

    assert owned == content_ids
    lookup.assert_awaited_once_with(db, learner, media_id)
