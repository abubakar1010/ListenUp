"""Bounds and failure handling of review.service.earlier_phrases (#74, FR-CA-4)."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from listenup.modules.review import service
from listenup.platform.errors import ProblemError

LEARNER = uuid.uuid4()
CURRENT = uuid.uuid4()


@dataclass
class Passage:
    words: list[str]


class FakeDb:
    def __init__(self) -> None:
        self.savepoints = 0

    @asynccontextmanager
    async def begin_nested(self):
        self.savepoints += 1
        yield


def sessions(count: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


@pytest.fixture
def reads(monkeypatch):
    """Newest first: a locked session, a broken one, then six readable ones."""
    locked, broken, *readable = sessions(8)
    ranges = [(locked, 0, 0), (broken, 0, 0)]
    ranges += [(other, 0, 1) for other in readable]
    ranges.append((readable[0], 2, 2))
    limits: list[int] = []
    read: list[uuid.UUID] = []

    async def other_session_ranges(db, learner, session_id, limit):
        assert (learner, session_id) == (LEARNER, CURRENT)
        limits.append(limit)
        return ranges

    async def read_passage(db, worker_database, learner, session_id):
        read.append(session_id)
        if session_id == locked:
            raise ProblemError(409, "step_locked", "Not yet.")
        if session_id == broken:
            raise RuntimeError("worker database went away")
        n = readable.index(session_id)
        return Passage([f"s{n}", "", f"x{n}"])

    monkeypatch.setattr(service.repository, "other_session_ranges", other_session_ranges)
    monkeypatch.setattr(service.transcript, "read_passage", read_passage)
    return locked, broken, readable, limits, read


@pytest.mark.anyio
async def test_reads_at_most_five_readable_sessions_and_skips_failures(reads):
    locked, broken, readable, limits, read = reads
    db = FakeDb()
    phrases = await service.earlier_phrases(db, object(), LEARNER, CURRENT)  # type: ignore[arg-type]
    assert limits == [service.EARLIER_MARKS]
    # Failed sessions do not use up a slot; the sixth readable one is never read.
    assert read == [locked, broken, *readable[:5]]
    assert phrases == ["s0", "x0", "s1", "s2", "s3", "s4"]
    assert db.savepoints == 7
