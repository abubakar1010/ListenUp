"""SQL for the practice module's sessions and steps (Database Design 5).

Every statement runs in the request's transaction as the API role, so row-level
security limits it to the current learner. Writes to a session go through
`update_session`, which bumps `version` only when it still has the expected value:
the optimistic check that catches two requests changing one session at once.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, text
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
    created_at: datetime
    updated_at: datetime


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
    updated_at: datetime


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


_SESSION_COLUMNS = """
SELECT id, user_id, content_id, passage, entry, status, version,
       entry_locked_at, completed_at, created_at, updated_at
  FROM practice.sessions
"""


def _session_row(row: Row[Any]) -> SessionRow:
    return SessionRow(
        id=row.id,
        user_id=row.user_id,
        content_id=row.content_id,
        passage=_passage(row.passage),
        entry=row.entry,
        status=row.status,
        version=row.version,
        entry_locked_at=row.entry_locked_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def find_session(
    session: AsyncSession, session_id: uuid.UUID
) -> tuple[SessionRow, list[StepRow]] | None:
    row = (
        await session.execute(text(_SESSION_COLUMNS + " WHERE id = :id"), {"id": session_id})
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
    return _session_row(row), [StepRow(s.step, s.position, s.status) for s in steps]


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
            RETURNING version, entry_locked_at, completed_at, updated_at
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
    if row is None:
        return None
    return Stamps(row.version, row.entry_locked_at, row.completed_at, row.updated_at)


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


async def latest_status_by_content(
    session: AsyncSession, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """The status of the newest session on each content item that has one."""
    if not content_ids:
        return {}
    rows = await session.execute(
        text("""
        SELECT DISTINCT ON (content_id) content_id, status
          FROM practice.sessions
         WHERE content_id = ANY(:content_ids)
         ORDER BY content_id, created_at DESC, id DESC
        """),
        {"content_ids": content_ids},
    )
    return {row.content_id: row.status for row in rows}


async def list_sessions(
    session: AsyncSession,
    learner: uuid.UUID,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[tuple[SessionRow, list[StepRow]]]:
    """The learner's sessions, most recently changed first, starting after `after`.

    Keyset on `sessions_user_idx` (user_id, updated_at DESC, id); the steps of the
    whole page come in one more query.
    """
    params: dict[str, object] = {"learner": learner, "limit": limit}
    where = "WHERE user_id = :learner"
    if after is not None:
        where += " AND (updated_at, id) < (:after_at, :after_id)"
        params.update(after_at=after[0], after_id=after[1])
    rows = (
        await session.execute(
            text(f"{_SESSION_COLUMNS} {where} ORDER BY updated_at DESC, id DESC LIMIT :limit"),
            params,
        )
    ).all()
    if not rows:
        return []
    step_rows = await session.execute(
        text("""
        SELECT session_id, step, position, status FROM practice.session_steps
         WHERE session_id = ANY(:ids) ORDER BY session_id, position
        """),
        {"ids": [row.id for row in rows]},
    )
    steps: dict[uuid.UUID, list[StepRow]] = {}
    for s in step_rows:
        steps.setdefault(s.session_id, []).append(StepRow(s.step, s.position, s.status))
    return [(_session_row(row), steps.get(row.id, [])) for row in rows]


# --- Attempts (migration 0008) ---------------------------------------------------------


@dataclass(frozen=True)
class AttemptRow:
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    mode: str
    status: str
    started_at: datetime
    finished_at: datetime | None


_ATTEMPT_COLUMNS = "id, session_id, user_id, mode, status, started_at, finished_at"


async def insert_attempt(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    mode: str,
) -> AttemptRow:
    row = (
        await session.execute(
            text(f"""
            INSERT INTO practice.attempts (id, session_id, user_id, mode)
            VALUES (:id, :session_id, :user_id, :mode)
            RETURNING {_ATTEMPT_COLUMNS}
            """),
            {"id": attempt_id, "session_id": session_id, "user_id": user_id, "mode": mode},
        )
    ).one()
    return AttemptRow(*row)


async def get_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> AttemptRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_ATTEMPT_COLUMNS} FROM practice.attempts WHERE id = :id"),
            {"id": attempt_id},
        )
    ).first()
    return AttemptRow(*row) if row else None


async def active_attempt(
    session: AsyncSession, session_id: uuid.UUID, mode: str
) -> AttemptRow | None:
    row = (
        await session.execute(
            text(f"""
            SELECT {_ATTEMPT_COLUMNS} FROM practice.attempts
             WHERE session_id = :session_id AND mode = :mode AND status = 'active'
            """),
            {"session_id": session_id, "mode": mode},
        )
    ).first()
    return AttemptRow(*row) if row else None


async def finish_attempt(
    session: AsyncSession, attempt_id: uuid.UUID, status: str
) -> AttemptRow | None:
    """Close an active attempt; None when it is not active (already closed or unknown)."""
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.attempts SET status = :status, finished_at = now()
             WHERE id = :id AND status = 'active'
            RETURNING {_ATTEMPT_COLUMNS}
            """),
            {"id": attempt_id, "status": status},
        )
    ).first()
    return AttemptRow(*row) if row else None
