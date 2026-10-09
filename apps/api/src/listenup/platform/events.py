"""Live updates over Server-Sent Events (System Design 9.1; Architecture 9.1; ADR 0016).

How an event travels:

1. Code that finishes work for a learner calls `publish(session, user_id, type, id)` in
   the transaction that stores the result. It runs `pg_notify('user_events', ...)`,
   which PostgreSQL delivers only when that transaction commits, so a rolled-back
   change never announces itself.
2. Each API process holds one `EventListener`: a dedicated autocommit connection that
   runs `LISTEN user_events` and reconnects on failure.
3. The listener hands each notification to the process's `EventHub`, which forwards
   it to that learner's open streams only and keeps it in a short per-learner replay
   buffer.
4. `GET /api/v1/events` streams the learner's events. A comment line every 25 s keeps
   proxies from closing an idle stream. On reconnect the browser sends
   `Last-Event-ID`: missed events are replayed from the buffer when it still holds
   them; otherwise the stream sends `resync` and the browser refetches whatever is
   still pending.

Payloads carry ids only, never data, so they stay far below PostgreSQL's 8000-byte
notification limit and never leak content: the browser fetches the resource itself,
through the normal access checks.
"""

import asyncio
import contextlib
import itertools
import json
import logging
import secrets
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHANNEL = "user_events"
LISTENER_APPLICATION_NAME = "listenup-events"
# Far below PostgreSQL's 8000-byte limit: an id-only payload is about 120 bytes.
MAX_PAYLOAD_BYTES = 1000
# How long the browser waits before reconnecting after the stream drops.
RETRY_MILLISECONDS = 3000


class EventType(StrEnum):
    JOB_PROGRESS = "job.progress"
    CONTENT_READY = "content.ready"
    GRADE_READY = "grade.ready"
    ATTEMPT_VOIDED = "attempt.voided"
    EXPORT_READY = "export.ready"  # a data export finished: ready or failed (#92)
    # The learner's account was disabled (deleted, ADR 0029). Their open streams get
    # this event and then end; reconnecting needs a login session, which is gone.
    ACCOUNT_DISABLED = "account.disabled"


STREAM_ENDING_EVENTS = frozenset({EventType.ACCOUNT_DISABLED})
"""Events after which the stream ends, whether sent live or replayed on reconnect."""


RESYNC = "resync"
"""Sent instead of events the stream cannot replay: refetch everything still pending."""


ResourceId = uuid.UUID | int | str


def notification_payload(user_id: uuid.UUID, event_type: EventType, resource_id: ResourceId) -> str:
    payload = json.dumps(
        {"u": str(user_id), "t": EventType(event_type).value, "r": str(resource_id)},
        separators=(",", ":"),
    )
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("an event carries ids only; this resource id is too long")
    return payload


async def publish(
    session: AsyncSession,
    user_id: uuid.UUID,
    event_type: EventType,
    resource_id: ResourceId,
) -> None:
    """Tell the learner's open streams that `resource_id` changed.

    Runs in the caller's transaction: the event is sent when it commits and never if
    it rolls back, so the browser cannot refetch a result that was not stored.
    """
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": notification_payload(user_id, event_type, resource_id)},
    )


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    resource_id: str

    def encode(self) -> str:
        data = json.dumps({"type": self.type, "resource_id": self.resource_id})
        return f"id: {self.id}\nevent: {self.type}\ndata: {data}\n\n"


class _Signal(Enum):
    RESYNC = "resync"
    CLOSE = "close"


RESYNC_MESSAGE = f'event: {RESYNC}\ndata: {{"type": "{RESYNC}"}}\n\n'
KEEP_ALIVE = ": keep-alive\n\n"

_Item = Event | _Signal


@dataclass(eq=False)
class Subscription:
    """One open stream. The hub fills its queue; the stream drains it."""

    user_id: uuid.UUID
    queue: asyncio.Queue[_Item]

    async def next(self, timeout: float) -> _Item | None:
        """The next item, or None when nothing arrived within `timeout` seconds."""
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None


@dataclass
class _Replay:
    events: deque[tuple[float, int, Event]] = field(default_factory=deque)
    # A browser whose last event is older than this sequence number may have missed
    # an event the buffer no longer holds.
    forgotten_through: int = 0


class EventHub:
    """In-memory fan-out from notifications to open streams, per learner.

    Event ids are `<hub id>-<sequence>`: the hub id is random per process, the
    sequence increases with every event. A reconnect that names this hub and a
    sequence the learner's buffer still covers gets the missed events replayed;
    any other reconnect (another process, a restart, an expired buffer) gets
    `resync`. Everything here runs on the event loop, so no locks are needed.
    """

    def __init__(
        self,
        *,
        replay_size: int = 50,
        replay_seconds: float = 120.0,
        queue_size: int = 100,
        keepalive_seconds: float = 25.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hub_id = secrets.token_hex(4)
        self.replay_size = replay_size
        self.replay_seconds = replay_seconds
        self.queue_size = queue_size
        self.keepalive_seconds = keepalive_seconds
        self._clock = clock
        self._sequence = itertools.count(1)
        self._last_sequence = 0
        self._streams: dict[uuid.UUID, set[Subscription]] = {}
        self._replay: dict[uuid.UUID, _Replay] = {}
        # The same, for learners without a buffer (never had one, or it was swept).
        self._forgotten_through = 0
        self._next_sweep = clock() + replay_seconds
        self._closed = False

    # -- incoming ------------------------------------------------------------------

    def dispatch(self, user_id: uuid.UUID, event_type: str, resource_id: str) -> Event:
        sequence = next(self._sequence)
        self._last_sequence = sequence
        event = Event(f"{self.hub_id}-{sequence}", event_type, resource_id)
        now = self._clock()
        replay = self._replay.get(user_id)
        if replay is None:
            replay = self._replay[user_id] = _Replay(forgotten_through=self._forgotten_through)
        replay.events.append((now, sequence, event))
        self._prune(replay, now)
        for subscription in self._streams.get(user_id, ()):
            self._put(subscription, event)
            if event_type in STREAM_ENDING_EVENTS:
                self._end(subscription)
        if now >= self._next_sweep:
            self._sweep(now)
        return event

    def dispatch_payload(self, payload: str) -> Event | None:
        """Forward one `user_events` notification; malformed ones are logged and dropped."""
        try:
            data = json.loads(payload)
            user_id = uuid.UUID(data["u"])
            event_type = EventType(data["t"])
            resource_id = str(data["r"])
        except (ValueError, KeyError, TypeError):
            logger.warning("ignored a malformed user event", extra={"payload": payload[:200]})
            return None
        return self.dispatch(user_id, event_type.value, resource_id)

    def mark_gap(self) -> None:
        """Notifications may have been missed (the listener reconnected).

        Every open stream gets `resync`, and no reconnect may rely on the replay
        buffer for events from before now.
        """
        # Lost notifications never got a sequence number, so even a browser that saw
        # the latest event may have missed something.
        self._forgotten_through = self._last_sequence + 1
        for replay in self._replay.values():
            replay.forgotten_through = self._forgotten_through
        for subscriptions in self._streams.values():
            for subscription in subscriptions:
                self._put(subscription, _Signal.RESYNC)

    # -- streams -------------------------------------------------------------------

    def subscribe(self, user_id: uuid.UUID, last_event_id: str | None = None) -> Subscription:
        subscription = Subscription(user_id, asyncio.Queue(self.queue_size))
        if self._closed:
            subscription.queue.put_nowait(_Signal.CLOSE)
            return subscription
        if last_event_id:
            missed = self._missed_since(user_id, last_event_id)
            if missed is None:
                self._put(subscription, _Signal.RESYNC)
            else:
                for event in missed:
                    self._put(subscription, event)
                    if event.type in STREAM_ENDING_EVENTS:
                        # As if live. Later events follow on the next reconnect, which
                        # names this event as the last one seen.
                        self._end(subscription)
                        return subscription
        self._streams.setdefault(user_id, set()).add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        streams = self._streams.get(subscription.user_id)
        if streams is None:
            return
        streams.discard(subscription)
        if not streams:
            del self._streams[subscription.user_id]

    def stream_count(self, user_id: uuid.UUID | None = None) -> int:
        if user_id is not None:
            return len(self._streams.get(user_id, ()))
        return sum(len(streams) for streams in self._streams.values())

    def close(self) -> None:
        """End every open stream (shutdown); browsers reconnect to another process."""
        self._closed = True
        for subscriptions in self._streams.values():
            for subscription in subscriptions:
                _drain(subscription.queue)
                subscription.queue.put_nowait(_Signal.CLOSE)

    # -- internals -----------------------------------------------------------------

    def _missed_since(self, user_id: uuid.UUID, last_event_id: str) -> list[Event] | None:
        """Events after `last_event_id`, or None when they cannot all be replayed."""
        hub_id, _, raw_sequence = last_event_id.strip().rpartition("-")
        if hub_id != self.hub_id or not raw_sequence.isdigit():
            return None
        sequence = int(raw_sequence)
        if sequence > self._last_sequence:
            return None
        replay = self._replay.get(user_id)
        if replay is None:
            return [] if sequence >= self._forgotten_through else None
        self._prune(replay, self._clock())
        if sequence < replay.forgotten_through:
            return None
        return [event for _, seq, event in replay.events if seq > sequence]

    def _prune(self, replay: _Replay, now: float) -> None:
        events = replay.events
        while events and (
            len(events) > self.replay_size or now - events[0][0] > self.replay_seconds
        ):
            _, sequence, _ = events.popleft()
            replay.forgotten_through = max(replay.forgotten_through, sequence)

    def _sweep(self, now: float) -> None:
        """Drop buffers whose events have all expired, so memory follows recent activity."""
        for user_id, replay in list(self._replay.items()):
            self._prune(replay, now)
            if not replay.events:
                self._forgotten_through = max(self._forgotten_through, replay.forgotten_through)
                del self._replay[user_id]
        self._next_sweep = now + self.replay_seconds

    def _put(self, subscription: Subscription, item: _Item) -> None:
        try:
            subscription.queue.put_nowait(item)
        except asyncio.QueueFull:
            # The stream cannot keep up: replace its backlog with one resync.
            _drain(subscription.queue)
            subscription.queue.put_nowait(_Signal.RESYNC)
            logger.warning("event stream fell behind; sent resync")

    def _end(self, subscription: Subscription) -> None:
        """End one stream after what is queued; a full queue ends it at once."""
        try:
            subscription.queue.put_nowait(_Signal.CLOSE)
        except asyncio.QueueFull:
            _drain(subscription.queue)
            subscription.queue.put_nowait(_Signal.CLOSE)


def _drain(queue: asyncio.Queue[_Item]) -> None:
    while not queue.empty():
        queue.get_nowait()


async def event_stream(
    hub: EventHub, user_id: uuid.UUID, last_event_id: str | None = None
) -> AsyncIterator[str]:
    """The text/event-stream body for one learner's stream.

    It subscribes when the body starts and unsubscribes when it ends, however it ends
    (the browser left, the server is shutting down), so no subscription outlives its
    stream. The first line arrives once the stream is subscribed.
    """
    subscription = hub.subscribe(user_id, last_event_id)
    try:
        yield f"retry: {RETRY_MILLISECONDS}\n: connected\n\n"
        while True:
            item = await subscription.next(hub.keepalive_seconds)
            if item is None:
                yield KEEP_ALIVE
            elif item is _Signal.CLOSE:
                return
            elif item is _Signal.RESYNC:
                yield RESYNC_MESSAGE
            else:
                assert isinstance(item, Event)
                yield item.encode()
    finally:
        hub.unsubscribe(subscription)


class EventListener:
    """The process's one `LISTEN user_events` connection, reconnecting on failure."""

    def __init__(
        self,
        database_url: str,
        hub: EventHub,
        *,
        ping_seconds: float = 30.0,
        first_retry_seconds: float = 0.5,
        max_retry_seconds: float = 30.0,
    ) -> None:
        self.database_url = database_url
        self.hub = hub
        self.ping_seconds = ping_seconds
        self.first_retry_seconds = first_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self.connected = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="event-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.connected.clear()

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                await self._listen()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.connected.clear()
                failures += 1
                delay = min(self.max_retry_seconds, self.first_retry_seconds * 2 ** (failures - 1))
                logger.warning(
                    "event listener lost its connection; reconnecting",
                    extra={"error": repr(error), "retry_in_seconds": delay},
                )
                await asyncio.sleep(delay)
            else:
                failures = 0

    async def _listen(self) -> None:
        conn = await psycopg.AsyncConnection.connect(
            self.database_url, autocommit=True, application_name=LISTENER_APPLICATION_NAME
        )
        async with conn:
            await conn.execute(f"LISTEN {CHANNEL}")
            # Anything sent while no connection was listening is lost: streams resync.
            self.hub.mark_gap()
            self.connected.set()
            while True:
                async for notify in conn.notifies(timeout=self.ping_seconds):
                    self.hub.dispatch_payload(notify.payload)
                # Quiet for a while: make sure the connection is still alive.
                await conn.execute("SELECT 1")


def get_event_hub(request: Request) -> EventHub:
    hub: EventHub = request.app.state.events
    return hub


def events_router(learner: Callable[..., Any]) -> APIRouter:
    """`GET /events`, guarded by `learner`, the dependency that resolves the signed-in user.

    The caller passes it in (identity's `current_learner`) so the platform package
    never imports a feature module.
    """
    router = APIRouter(tags=["events"])

    @router.get(
        "/events",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": (
                    "A Server-Sent Events stream of the learner's events: "
                    "job.progress, content.ready, grade.ready, attempt.voided, export.ready, "
                    "account.disabled (the stream then ends) and resync."
                ),
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    async def events(
        request: Request,
        user_id: Annotated[uuid.UUID, Depends(learner)],
        hub: Annotated[EventHub, Depends(get_event_hub)],
        last_event_id: Annotated[str | None, Header(max_length=100)] = None,
    ) -> StreamingResponse:
        """Stream the learner's live events (System Design 9.1).

        Each event carries only its type and the id of the resource to refetch.
        """
        return StreamingResponse(
            event_stream(hub, user_id, last_event_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
