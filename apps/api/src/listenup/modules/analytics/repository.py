"""SQL for `ops.analytics_events` (migration 0015, ADR 0033).

Inserts run in the caller's transaction. As the API role, row-level security limits
them to the current learner, and the role may not read the table back; the report
reads it as `listenup_readonly` (or the owner), which sees every learner.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics.domain import REPORT_EVENT_TYPES, REPORT_STEPS, Event, EventType
from listenup.platform.ids import uuid7

_INSERT = text("""
INSERT INTO ops.analytics_events
  (id, user_id, event_type, subject_id, step, content_id, session_id, properties)
VALUES
  (:id, :user_id, :event_type, :subject_id, :step, :content_id, :session_id,
   CAST(:properties AS jsonb))
ON CONFLICT DO NOTHING
""")


@dataclass(frozen=True)
class NewEvent:
    event_type: EventType
    subject_id: uuid.UUID
    step: str | None = None
    content_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    properties: dict[str, Any] | None = None


async def insert_many(
    session: AsyncSession, user_id: uuid.UUID, events: Sequence[NewEvent]
) -> None:
    """Record events in one statement round; one already recorded is skipped.

    `ON CONFLICT DO NOTHING` needs no read access, so the API role keeps INSERT only.
    """
    if not events:
        return
    await session.execute(
        _INSERT,
        [
            {
                "id": uuid7(),
                "user_id": user_id,
                "event_type": event.event_type.value,
                "subject_id": event.subject_id,
                "step": event.step,
                "content_id": event.content_id,
                "session_id": event.session_id,
                "properties": json.dumps(event.properties or {}),
            }
            for event in events
        ],
    )


async def insert(session: AsyncSession, user_id: uuid.UUID, event: NewEvent) -> None:
    """Record one event; nothing happens when the same occurrence is already recorded."""
    await insert_many(session, user_id, [event])


async def events_before(session: AsyncSession, as_of: datetime) -> list[Event]:
    """The events the report reads that happened before `as_of`, oldest first.

    The report follows each cohort to `as_of` and needs every learner's earlier plans
    and marks, so it reads history rather than the range alone. It reads only the event
    types and steps the metrics use; the high-volume step events of the other steps stay
    in the table. Beta volumes are small; aggregating in SQL is the step to take when
    they are not.
    """
    result = await session.execute(
        text("""
        SELECT event_type, user_id, subject_id, occurred_at, step, content_id, session_id,
               properties
          FROM ops.analytics_events
         WHERE occurred_at < :as_of
           AND event_type = ANY(:types)
           AND (step IS NULL OR step = ANY(:steps))
         ORDER BY occurred_at, id
        """),
        {
            "as_of": as_of,
            "types": [kind.value for kind in REPORT_EVENT_TYPES],
            "steps": list(REPORT_STEPS),
        },
    )
    return [
        Event(
            type=EventType(row.event_type),
            user_id=row.user_id,
            subject_id=row.subject_id,
            occurred_at=row.occurred_at,
            step=row.step,
            content_id=row.content_id,
            session_id=row.session_id,
            properties=row.properties,
        )
        for row in result
    ]
