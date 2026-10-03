"""SQL for the practice module's sessions and steps (Database Design 5).

Every statement runs in the request's transaction as the API role, so row-level
security limits it to the current learner. Writes to a session go through
`update_session`, which bumps `version` only when it still has the expected value:
the optimistic check that catches two requests changing one session at once.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.practice.domain import Passage, StepState, StepStatus

FINISHED = (StepStatus.DONE, StepStatus.SKIPPED)


@dataclass(frozen=True)
class SessionRow:
    id: uuid.UUID
    user_id: uuid.UUID
    content_id: uuid.UUID
    passage: Passage
    entry: str
    status: str
    version: int
    entry_locked_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class StepRow:
    step: str
    position: int
    status: str


@dataclass(frozen=True)
class SessionUpdate:
    entry: str
    current_step: str
    status: str
    lock_entry: bool
    completed: bool


@dataclass(frozen=True)
class Stamps:
    version: int
    entry_locked_at: datetime | None
    completed_at: datetime | None


def _passage(value: Range[int]) -> Passage:
    assert value.lower is not None and value.upper is not None  # sessions_passage_bounded
    return Passage(value.lower, value.upper)


async def insert_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    content_id: uuid.UUID,
    passage: Passage,
    entry: str,
    current_step: str,
) -> bool:
    """False when the learner has no such content item (row-level security hides others')."""
    result = await session.execute(
        text("""
        INSERT INTO practice.sessions (id, user_id, content_id, passage, entry, current_step)
        SELECT :id, :user_id, :content_id, int4range(:start, :end), :entry, :current_step
         WHERE EXISTS (SELECT 1 FROM content.contents WHERE id = :content_id)
        RETURNING id
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "content_id": content_id,
            "start": passage.start_ms,
            "end": passage.end_ms,
            "entry": entry,
            "current_step": current_step,
        },
    )
    return result.first() is not None


async def insert_steps(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, steps: list[StepState]
) -> None:
    """Insert steps in position order, so the order trigger sees each step's predecessor."""
    for state in sorted(steps, key=lambda s: s.position):
        await session.execute(
            text("""
            INSERT INTO practice.session_steps
              (session_id, user_id, step, position, status, opened_at)
            VALUES (:session_id, :user_id, :step, :position, :status,
                    CASE WHEN :status = 'open' THEN now() END)
            """),
            {
                "session_id": session_id,
                "user_id": user_id,
                "step": state.step.value,
                "position": state.position,
                "status": state.status.value,
            },
        )


async def find_session(
    session: AsyncSession, session_id: uuid.UUID
) -> tuple[SessionRow, list[StepRow]] | None:
    row = (
        await session.execute(
            text("""
            SELECT id, user_id, content_id, passage, entry, status, version,
                   entry_locked_at, completed_at
              FROM practice.sessions WHERE id = :id
            """),
            {"id": session_id},
        )
    ).first()
    if row is None:
        return None
    steps = (
        await session.execute(
            text("""
            SELECT step, position, status FROM practice.session_steps
             WHERE session_id = :id ORDER BY position
            """),
            {"id": session_id},
        )
    ).all()
    found = SessionRow(
        id=row.id,
        user_id=row.user_id,
        content_id=row.content_id,
        passage=_passage(row.passage),
        entry=row.entry,
        status=row.status,
        version=row.version,
        entry_locked_at=row.entry_locked_at,
        completed_at=row.completed_at,
    )
    return found, [StepRow(s.step, s.position, s.status) for s in steps]


async def update_session(
    session: AsyncSession, session_id: uuid.UUID, expected_version: int, change: SessionUpdate
) -> Stamps | None:
    """Write the session row if nobody changed it since `expected_version`; else None."""
    row = (
        await session.execute(
            text("""
            UPDATE practice.sessions
               SET entry = :entry,
                   current_step = :current_step,
                   status = :status,
                   entry_locked_at = CASE WHEN :lock_entry
                                          THEN coalesce(entry_locked_at, now())
                                          ELSE entry_locked_at END,
                   completed_at = CASE WHEN :completed
                                       THEN coalesce(completed_at, now())
                                       ELSE completed_at END,
                   version = version + 1
             WHERE id = :id AND version = :version
            RETURNING version, entry_locked_at, completed_at
            """),
            {
                "id": session_id,
                "version": expected_version,
                "entry": change.entry,
                "current_step": change.current_step,
                "status": change.status,
                "lock_entry": change.lock_entry,
                "completed": change.completed,
            },
        )
    ).first()
    return Stamps(row.version, row.entry_locked_at, row.completed_at) if row else None


async def update_steps(
    session: AsyncSession, session_id: uuid.UUID, steps: list[StepState]
) -> None:
    """Write changed step statuses in position order: a step finishes before the next opens."""
    for state in sorted(steps, key=lambda s: s.position):
        await session.execute(
            text("""
            UPDATE practice.session_steps
               SET status = :status,
                   opened_at = CASE WHEN :status = 'open' THEN now() ELSE opened_at END,
                   completed_at = CASE WHEN :status IN ('done', 'skipped') THEN now()
                                       ELSE completed_at END
             WHERE session_id = :session_id AND step = :step
            """),
            {"session_id": session_id, "step": state.step.value, "status": state.status.value},
        )


async def delete_unfinished_steps(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(
        text("""
        DELETE FROM practice.session_steps
         WHERE session_id = :session_id AND status NOT IN ('done', 'skipped')
        """),
        {"session_id": session_id},
    )
