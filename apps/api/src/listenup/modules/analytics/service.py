"""The analytics module's public API: record product events, export them, report on them.

#101, PRD 2 and 8.2, ADR 0033. Other modules use only this file (Architecture 4.3),
with one call per place where an event happens, inside the transaction that makes the
change, so the event and the change commit or roll back together:

- `record_content_added`: content (`Uploads.confirm`; YouTube intake later).
- `record_plan_started` and `record_plan_progress`: practice (`start_session` and
  every step transition); they derive `step_started` and `step_completed`.
- `record_listen_started`: practice (`start_attempt`, Blind and Dictation).
- `record_blind_abandoned`: blind (an attempt voided).
- `record_dictation_replays`: Dictation submission (#53), not built yet.
- `record_mark_created`, `record_card_created`, `record_shadow_round_completed`: the
  marks, Card and Shadow features, not built yet.

Each occurrence is recorded once: a repeat of the same (event, subject, step) is
ignored by the table's unique key. The functions take plain values, and this module
imports no other module (an import-linter contract), so any module may call it.
Events hold the learner's id and nothing else personal.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.analytics import repository
from listenup.modules.analytics.domain import (
    LISTEN_MODES,
    PATHS,
    SOURCE_TYPES,
    EventType,
    Report,
    compute_report,
    mark_pattern,
    require_one_of,
    step_changes,
)
from listenup.platform.export import ExportPart, learner_rows

__all__ = [
    "EventType",
    "Report",
    "build_report",
    "export_data",
    "record_blind_abandoned",
    "record_card_created",
    "record_content_added",
    "record_dictation_replays",
    "record_listen_started",
    "record_mark_created",
    "record_plan_progress",
    "record_plan_started",
    "record_shadow_round_completed",
]


async def record_content_added(
    db: AsyncSession, learner: uuid.UUID, content_id: uuid.UUID, *, source_type: str
) -> None:
    """A new content item, with where it came from ('upload' or 'youtube')."""
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.CONTENT_ADDED,
        subject_id=content_id,
        content_id=content_id,
        properties={"source_type": require_one_of("source_type", source_type, SOURCE_TYPES)},
    )


async def record_plan_started(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    content_id: uuid.UUID,
    *,
    path: str,
    steps: dict[str, str],
) -> None:
    """A new session with its entry path, and the step it opens on (`step_started`).

    `steps` is the plan as {step: status}.
    """
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.PLAN_STARTED,
        subject_id=session_id,
        content_id=content_id,
        session_id=session_id,
        properties={"path": require_one_of("path", path, PATHS)},
    )
    await record_plan_progress(db, learner, session_id, content_id, before={}, after=steps)


async def record_plan_progress(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    content_id: uuid.UUID,
    *,
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    """`step_completed` and `step_started` for a transition of the plan, as {step: status}."""
    for change in step_changes(before, after):
        await repository.insert(
            db,
            user_id=learner,
            event_type=change.event,
            subject_id=session_id,
            step=change.step,
            content_id=content_id,
            session_id=session_id,
            properties={"outcome": change.outcome} if change.outcome else None,
        )


async def record_listen_started(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    content_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    mode: str,
) -> None:
    """An attempt at Blind or Dictation began: the learner is about to listen."""
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.LISTEN_STARTED,
        subject_id=attempt_id,
        content_id=content_id,
        session_id=session_id,
        properties={"mode": require_one_of("mode", mode, LISTEN_MODES)},
    )


async def record_blind_abandoned(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    reason: str,
) -> None:
    """A Blind attempt was voided, with the reason (left_page, seek, interrupted ...)."""
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.BLIND_ABANDONED,
        subject_id=attempt_id,
        session_id=session_id,
        properties={"reason": reason[:50]},
    )


async def record_dictation_replays(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    replay_count: int,
) -> None:
    """How often the learner replayed in one Dictation attempt; called on submission (#53)."""
    if replay_count < 0:
        raise ValueError("a replay count cannot be negative")
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.DICTATION_REPLAYS,
        subject_id=attempt_id,
        session_id=session_id,
        properties={"replay_count": replay_count},
    )


async def record_mark_created(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    mark_id: uuid.UUID,
    *,
    phrase: str,
) -> None:
    """A mark was made; only a hash of its normalised phrase is kept (repeat failures)."""
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.MARK_CREATED,
        subject_id=mark_id,
        session_id=session_id,
        properties={"pattern": mark_pattern(phrase)},
    )


async def record_card_created(
    db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID, card_id: uuid.UUID
) -> None:
    """A card was made (always from a mark, FR-CA-2)."""
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.CARD_CREATED,
        subject_id=card_id,
        session_id=session_id,
    )


async def record_shadow_round_completed(
    db: AsyncSession,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    round_id: uuid.UUID,
    *,
    round_number: int,
) -> None:
    """A Shadow round (1 to 3) was completed."""
    if round_number not in (1, 2, 3):
        raise ValueError("a Shadow round is numbered 1 to 3")
    await repository.insert(
        db,
        user_id=learner,
        event_type=EventType.SHADOW_ROUND_COMPLETED,
        subject_id=round_id,
        session_id=session_id,
        properties={"round": round_number},
    )


async def build_report(db: AsyncSession, start: datetime, end: datetime, as_of: datetime) -> Report:
    """The five PRD 2 metrics for [start, end), following events up to `as_of`.

    Run it as `listenup_readonly` (scripts/analytics_report.py), which sees every
    learner's events but no account data.
    """
    return compute_report(await repository.events_before(db, as_of), start, end, as_of)


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    """The learner's analytics events for their data export (#92, ADR 0033)."""
    table = await learner_rows(session, "ops.analytics_events", learner, order_by="occurred_at")
    return ExportPart(tables=(table,))
