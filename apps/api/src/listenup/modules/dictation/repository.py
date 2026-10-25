"""SQL for Dictation drafts (`practice.dictation_attempts`, migration 0010).

Every statement runs in the request's transaction as the API role, so row-level
security limits it to the current learner. Nothing here reads a transcript: the
reference text belongs to the transcript module and Dictation never shows it
(FR-DI-3, FR-TX-5).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DraftRow:
    attempt_id: uuid.UUID
    draft_text: str
    draft_version: int
    updated_at: datetime


_COLUMNS = "attempt_id, draft_text, draft_version, updated_at"


async def ensure_draft(
    session: AsyncSession, attempt_id: uuid.UUID, user_id: uuid.UUID
) -> DraftRow:
    """The attempt's draft row, created empty if it has none yet (safe to repeat)."""
    await session.execute(
        text("""
        INSERT INTO practice.dictation_attempts (attempt_id, user_id)
        VALUES (:attempt_id, :user_id)
        ON CONFLICT (attempt_id) DO NOTHING
        """),
        {"attempt_id": attempt_id, "user_id": user_id},
    )
    found = await get_draft(session, attempt_id)
    assert found is not None  # just inserted or already there, and the learner's own
    return found


async def get_draft(session: AsyncSession, attempt_id: uuid.UUID) -> DraftRow | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM practice.dictation_attempts WHERE attempt_id = :id"),
            {"id": attempt_id},
        )
    ).first()
    return DraftRow(*row) if row else None


async def save_draft(
    session: AsyncSession, attempt_id: uuid.UUID, draft_text: str, base_version: int
) -> DraftRow | None:
    """Write the draft if it is still at `base_version`, bumping the version; else None."""
    row = (
        await session.execute(
            text(f"""
            UPDATE practice.dictation_attempts
               SET draft_text = :draft_text, draft_version = draft_version + 1
             WHERE attempt_id = :id AND draft_version = :base_version
            RETURNING {_COLUMNS}
            """),
            {"id": attempt_id, "draft_text": draft_text, "base_version": base_version},
        )
    ).first()
    return DraftRow(*row) if row else None


ScoringStatus = Literal["waiting_transcript", "scoring_unavailable", "scored"]
DiffStatus = Literal["correct", "spelling_slip", "wrong", "missing", "extra", "not_scored"]
"""The stored vocabularies; the API schemas use the same types, so a new one cannot
reach a response without a decision (and a failing type check) here."""

WAITING: ScoringStatus = "waiting_transcript"
UNAVAILABLE: ScoringStatus = "scoring_unavailable"
SCORED: ScoringStatus = "scored"


async def store_submission(session: AsyncSession, attempt_id: uuid.UUID, submitted: str) -> None:
    """Keep the submitted text; it waits for scoring (`waiting_transcript`, ADR 0042)."""
    await session.execute(
        text("""
        UPDATE practice.dictation_attempts
           SET submitted_text = :submitted, scoring_status = :waiting,
               diff = NULL, accuracy = NULL, scored_at = NULL
         WHERE attempt_id = :id
        """),
        {"id": attempt_id, "submitted": submitted, "waiting": WAITING},
    )


@dataclass(frozen=True)
class WaitingRow:
    attempt_id: uuid.UUID
    session_id: uuid.UUID
    submitted_text: str


_WAITING = """
SELECT d.attempt_id, a.session_id, d.submitted_text
  FROM practice.dictation_attempts d JOIN practice.attempts a ON a.id = d.attempt_id
 WHERE d.scoring_status IN ('waiting_transcript', 'scoring_unavailable')
"""


async def get_waiting(session: AsyncSession, attempt_id: uuid.UUID) -> WaitingRow | None:
    """The submission still without a score, or None (scored, or not submitted).

    A submission whose transcript failed (`scoring_unavailable`) counts: a later
    successful transcription scores it.
    """
    row = (
        await session.execute(text(_WAITING + " AND d.attempt_id = :id"), {"id": attempt_id})
    ).first()
    return WaitingRow(*row) if row else None


async def waiting_in_session(session: AsyncSession, session_id: uuid.UUID) -> list[WaitingRow]:
    rows = await session.execute(text(_WAITING + " AND a.session_id = :sid"), {"sid": session_id})
    return [WaitingRow(*row) for row in rows]


async def mark_unavailable(session: AsyncSession, attempt_id: uuid.UUID) -> bool:
    """Record that the transcript failed; False unless the submission was waiting.

    Conditional like `store_score`, so a repeat announces nothing and a score is never undone.
    """
    row = (
        await session.execute(
            text("""
            UPDATE practice.dictation_attempts SET scoring_status = 'scoring_unavailable'
             WHERE attempt_id = :id AND scoring_status = 'waiting_transcript'
            RETURNING 1
            """),
            {"id": attempt_id},
        )
    ).first()
    return row is not None


async def store_score(
    session: AsyncSession, attempt_id: uuid.UUID, diff: dict[str, object], accuracy: object
) -> bool:
    """Write the score unless the submission is already scored; False then.

    One conditional update, so two runs of the job store one score and announce once.
    """
    row = (
        await session.execute(
            text("""
            UPDATE practice.dictation_attempts
               SET scoring_status = 'scored', diff = :diff, accuracy = :accuracy, scored_at = now()
             WHERE attempt_id = :id
               AND scoring_status IN ('waiting_transcript', 'scoring_unavailable')
            RETURNING 1
            """).bindparams(bindparam("diff", type_=JSONB)),
            {"id": attempt_id, "diff": diff, "accuracy": accuracy},
        )
    ).first()
    return row is not None


@dataclass(frozen=True)
class SubmissionRow:
    scoring_status: ScoringStatus | None
    diff: dict[str, Any] | None
    accuracy: Decimal | None


async def get_submission(session: AsyncSession, attempt_id: uuid.UUID) -> SubmissionRow | None:
    row = (
        await session.execute(
            text(
                "SELECT scoring_status, diff, accuracy FROM practice.dictation_attempts "
                "WHERE attempt_id = :id"
            ),
            {"id": attempt_id},
        )
    ).first()
    return SubmissionRow(*row) if row else None


async def latest_submitted_attempt(
    session: AsyncSession, session_id: uuid.UUID
) -> uuid.UUID | None:
    """The session's newest attempt that has a submission, or None."""
    row = (
        await session.execute(
            text("""
            SELECT d.attempt_id FROM practice.dictation_attempts d
              JOIN practice.attempts a ON a.id = d.attempt_id
             WHERE a.session_id = :sid AND d.scoring_status IS NOT NULL
             ORDER BY a.started_at DESC, a.id DESC LIMIT 1
            """),
            {"sid": session_id},
        )
    ).first()
    return row[0] if row else None


async def rescore(
    session: AsyncSession, attempt_id: uuid.UUID, diff: dict[str, object], accuracy: object
) -> None:
    await session.execute(
        text("""
        UPDATE practice.dictation_attempts SET diff=:diff, accuracy=:accuracy, scored_at=now()
         WHERE attempt_id=:id AND scoring_status='scored'
        """).bindparams(bindparam("diff", type_=JSONB)),
        {"id": attempt_id, "diff": diff, "accuracy": accuracy},
    )


async def submitted_text(session: AsyncSession, attempt_id: uuid.UUID) -> str:
    value = await session.scalar(
        text("SELECT submitted_text FROM practice.dictation_attempts WHERE attempt_id=:id"),
        {"id": attempt_id},
    )
    assert isinstance(value, str)
    return value
