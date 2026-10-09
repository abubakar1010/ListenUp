"""The in-memory event hub and the SSE stream body (#30; System Design 9.1, ADR 0016)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pytest

from listenup.platform.events import (
    KEEP_ALIVE,
    RESYNC_MESSAGE,
    EventHub,
    EventType,
    event_stream,
    notification_payload,
)

pytestmark = pytest.mark.anyio

A = uuid.UUID("00000000-0000-7000-8000-00000000000a")
B = uuid.UUID("00000000-0000-7000-8000-00000000000b")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def drain(stream: AsyncIterator[str], count: int, timeout: float = 1.0) -> list[str]:
    return [await asyncio.wait_for(anext(stream), timeout) for _ in range(count)]


def parse(chunk: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in chunk.strip().splitlines():
        name, _, value = line.partition(": ")
        fields[name] = value
    return fields


async def opened(
    hub: EventHub, user: uuid.UUID, last_event_id: str | None = None
) -> AsyncIterator[str]:
    stream = event_stream(hub, user, last_event_id)
    first = await anext(stream)
    assert first.startswith("retry: ")  # subscribed from here on
    return stream


async def test_an_event_reaches_every_stream_of_its_learner_and_no_other() -> None:
    hub = EventHub()
    a1, a2, b = await opened(hub, A), await opened(hub, A), await opened(hub, B)

    sent = hub.dispatch(A, "content.ready", "clip-1")

    for stream in (a1, a2):
        (chunk,) = await drain(stream, 1)
        fields = parse(chunk)
        assert fields["id"] == sent.id
        assert fields["event"] == "content.ready"
        assert json.loads(fields["data"]) == {"type": "content.ready", "resource_id": "clip-1"}
    assert hub.stream_count(A) == 2
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(b), 0.05)


async def test_an_idle_stream_sends_a_comment_line() -> None:
    hub = EventHub(keepalive_seconds=0.02)
    stream = await opened(hub, A)

    assert await drain(stream, 2) == [KEEP_ALIVE, KEEP_ALIVE]


async def test_a_closed_stream_unsubscribes() -> None:
    hub = EventHub()
    stream = await opened(hub, A)
    assert hub.stream_count() == 1

    await stream.aclose()  # type: ignore[attr-defined]

    assert hub.stream_count() == 0


async def test_shutdown_ends_every_stream() -> None:
    hub = EventHub()
    stream = await opened(hub, A)

    hub.close()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1)
    assert hub.stream_count() == 0


async def test_a_reconnect_replays_what_the_learner_missed() -> None:
    hub = EventHub()
    seen = hub.dispatch(A, "job.progress", "job-1")
    missed = [hub.dispatch(A, "job.progress", "job-1"), hub.dispatch(A, "grade.ready", "g-1")]
    hub.dispatch(B, "grade.ready", "g-2")

    stream = await opened(hub, A, last_event_id=seen.id)

    chunks = await drain(stream, 2)
    assert [parse(chunk)["id"] for chunk in chunks] == [event.id for event in missed]
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.05)


async def test_a_reconnect_with_nothing_missed_replays_nothing() -> None:
    hub = EventHub()
    last = hub.dispatch(A, "content.ready", "clip-1")

    stream = await opened(hub, A, last_event_id=last.id)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.05)


@pytest.mark.parametrize("last_event_id", ["0badc0de-1", "garbage", "-", "x-y"])
async def test_an_id_from_another_process_asks_for_a_resync(last_event_id: str) -> None:
    hub = EventHub()
    hub.dispatch(A, "content.ready", "clip-1")

    stream = await opened(hub, A, last_event_id=last_event_id)

    assert await drain(stream, 1) == [RESYNC_MESSAGE]


async def test_an_id_from_the_future_asks_for_a_resync() -> None:
    hub = EventHub()

    stream = await opened(hub, A, last_event_id=f"{hub.hub_id}-99")

    assert await drain(stream, 1) == [RESYNC_MESSAGE]


async def test_a_reconnect_past_the_buffer_asks_for_a_resync() -> None:
    hub = EventHub(replay_size=2)
    first = hub.dispatch(A, "job.progress", "job-1")
    for _ in range(3):
        hub.dispatch(A, "job.progress", "job-1")

    stream = await opened(hub, A, last_event_id=first.id)

    assert await drain(stream, 1) == [RESYNC_MESSAGE]


async def test_expired_buffers_are_swept_and_their_ids_resync() -> None:
    clock = Clock()
    hub = EventHub(replay_seconds=60, clock=clock)
    seen = hub.dispatch(A, "content.ready", "clip-1")
    hub.dispatch(A, "content.ready", "clip-2")  # missed, and expires with the buffer
    clock.now += 61
    hub.dispatch(B, "content.ready", "clip-2")  # triggers the sweep

    assert A not in hub._replay
    stream = await opened(hub, A, last_event_id=seen.id)
    assert await drain(stream, 1) == [RESYNC_MESSAGE]


async def test_a_gap_in_listening_resyncs_open_streams_and_old_ids() -> None:
    hub = EventHub()
    before = hub.dispatch(A, "content.ready", "clip-1")
    stream = await opened(hub, A)

    hub.mark_gap()

    assert await drain(stream, 1) == [RESYNC_MESSAGE]
    late = await opened(hub, A, last_event_id=before.id)
    assert await drain(late, 1) == [RESYNC_MESSAGE]


async def test_a_stream_that_falls_behind_gets_a_resync_instead_of_its_backlog() -> None:
    hub = EventHub(queue_size=3)
    stream = await opened(hub, A)

    for n in range(4):
        hub.dispatch(A, "job.progress", f"job-{n}")

    assert await drain(stream, 1) == [RESYNC_MESSAGE]
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.05)


async def test_payloads_from_postgres_are_parsed_and_bad_ones_dropped() -> None:
    hub = EventHub()
    stream = await opened(hub, A)

    assert hub.dispatch_payload("not json") is None
    assert hub.dispatch_payload(json.dumps({"u": str(A), "t": "secret.data", "r": "1"})) is None
    assert hub.dispatch_payload(json.dumps({"u": "nobody", "t": "grade.ready", "r": "1"})) is None
    event = hub.dispatch_payload(notification_payload(A, EventType.GRADE_READY, 42))

    assert event is not None
    (chunk,) = await drain(stream, 1)
    assert parse(chunk)["id"] == event.id
    assert json.loads(parse(chunk)["data"]) == {"type": "grade.ready", "resource_id": "42"}


def test_a_payload_carries_ids_only() -> None:
    payload = notification_payload(A, EventType.CONTENT_READY, B)

    assert json.loads(payload) == {"u": str(A), "t": "content.ready", "r": str(B)}
    with pytest.raises(ValueError):
        notification_payload(A, EventType.CONTENT_READY, "x" * 2000)
    with pytest.raises(ValueError):
        notification_payload(A, "transcript.text", "1")  # type: ignore[arg-type]


async def test_a_disabled_account_gets_the_event_and_its_streams_end() -> None:
    """Deleting an account (ADR 0029) ends its open streams; others keep theirs."""
    hub = EventHub()
    a1, a2, b = await opened(hub, A), await opened(hub, A), await opened(hub, B)
    hub.dispatch(A, "content.ready", "clip-1")

    hub.dispatch(A, EventType.ACCOUNT_DISABLED.value, str(A))

    for stream in (a1, a2):
        first, second = await drain(stream, 2)
        assert parse(first)["event"] == "content.ready"
        assert parse(second)["event"] == "account.disabled"
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), 1.0)
    assert hub.stream_count(A) == 0
    assert hub.stream_count(B) == 1
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(b), 0.05)


async def test_a_full_stream_of_a_disabled_account_still_ends() -> None:
    hub = EventHub(queue_size=2)
    stream = await opened(hub, A)
    for number in range(5):
        hub.dispatch(A, "job.progress", f"clip-{number}")

    disabled = hub.dispatch(A, EventType.ACCOUNT_DISABLED.value, str(A))

    chunks = await drain(stream, 2)
    assert parse(chunks[-1])["id"] == disabled.id
    assert parse(chunks[-1])["event"] == "account.disabled"
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1.0)


async def test_a_replayed_stream_ending_event_ends_the_stream_too() -> None:
    """A reconnect that replays `account.disabled` ends like a live one (ADR 0029);
    the events after it come on the next reconnect, which names it as last seen."""
    hub = EventHub()
    seen = hub.dispatch(A, "content.ready", "clip-1")
    disabled = hub.dispatch(A, EventType.ACCOUNT_DISABLED.value, str(A))
    later = hub.dispatch(A, "content.ready", "clip-2")  # restored, then a clip finished

    stream = await opened(hub, A, last_event_id=seen.id)

    (chunk,) = await drain(stream, 1)
    assert parse(chunk)["id"] == disabled.id
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1.0)
    assert hub.stream_count(A) == 0

    again = await opened(hub, A, last_event_id=disabled.id)
    (chunk,) = await drain(again, 1)
    assert parse(chunk)["id"] == later.id
    assert hub.stream_count(A) == 1
