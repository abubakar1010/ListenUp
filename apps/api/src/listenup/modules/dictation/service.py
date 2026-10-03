"""The dictation module's public API: the Dictation step's attempt and its draft.

#51 and #52 (FR-DI-1 to FR-DI-4, FR-PL-6, NFR-REL-1), ADR 0025:

- `open_attempt` starts the learner's Dictation attempt at an open Dictation step, or
  resumes the live one with its draft. Dictation never voids an attempt on leave or
  reload, unlike Blind: typed work must survive a refresh, a closed tab and a lost
  connection.
- `save_draft` writes the draft only if it is still at the version the client last
  saw. A stale save is refused with 409 `draft_conflict`, carrying the current draft,
  so two tabs never silently overwrite each other (#50). Resending a save whose answer
  was lost is not a conflict: the server already holds that text.

Nothing here reads or returns reference text: Dictation hides the transcript
(FR-DI-3, FR-TX-5). Submission and scoring (#53, #54) are not built yet; they will
fill the submission columns of the same row and call `practice.finish_attempt` and
`practice.complete_step`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.dictation import repository
from listenup.modules.practice import service as practice
from listenup.modules.practice.service import Attempt, AttemptStatus, Passage, Step
from listenup.platform.errors import ProblemError

__all__ = [
    "MAX_DRAFT_CHARS",
    "DictationWork",
    "Draft",
    "open_attempt",
    "save_draft",
]

MAX_DRAFT_CHARS = 20_000
"""The longest draft, in characters; the table's CHECK has the same limit."""


@dataclass(frozen=True)
class Draft:
    text: str
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class DictationWork:
    """What the Dictation screen needs: the attempt, its draft and what to play."""

    attempt: Attempt
    draft: Draft
    passage: Passage
    media_object_id: uuid.UUID
    resumed: bool


def _draft(row: repository.DraftRow) -> Draft:
    return Draft(row.draft_text, row.draft_version, row.updated_at)


def _not_found() -> ProblemError:
    return ProblemError(404, "attempt_not_found", "This attempt was not found.")


async def open_attempt(
    db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID
) -> DictationWork:
    """Start or resume the Dictation attempt of a session whose Dictation step is open.

    404 `session_not_found`; 409 `step_locked` (with `open_step`) unless Dictation is
    the open step, `step_not_in_plan` or `session_closed`, all from `require_step`.
    """
    session = await practice.require_step(db, session_id, Step.DICTATION)
    attempt = await practice.active_attempt(db, session.id, Step.DICTATION)
    resumed = attempt is not None
    if attempt is None:
        try:
            attempt = await practice.start_attempt(db, session.id, Step.DICTATION)
        except ProblemError as error:
            # Another tab started one at the same moment: resume that one.
            if error.code != "attempt_active":
                raise
            attempt = await practice.active_attempt(db, session.id, Step.DICTATION)
            if attempt is None:  # pragma: no cover - it was active a moment ago
                raise
            resumed = True
    draft = await repository.ensure_draft(db, attempt.id, learner)
    clip = await content.get_content(db, learner, session.content_id)
    return DictationWork(attempt, _draft(draft), session.passage, clip.media_object_id, resumed)


async def save_draft(
    db: AsyncSession, attempt_id: uuid.UUID, text: str, base_version: int
) -> Draft:
    """Save the draft typed in the Dictation text area (FR-DI-4, NFR-PERF-3).

    - 422 `draft_too_long` over MAX_DRAFT_CHARS characters (with `max_chars`).
    - 404 `attempt_not_found` for another learner's attempt, or one that is not
      Dictation.
    - 409 `step_locked`, `session_closed` and the other refusals of `require_step`
      when the Dictation step is no longer open.
    - 409 `attempt_closed` once the attempt has been submitted or voided.
    - 409 `draft_conflict` when the draft is no longer at `base_version`: another tab
      or browser saved since. The problem carries the current `draft_text`,
      `draft_version` and `updated_at`, so the client can show both versions.
    """
    if len(text) > MAX_DRAFT_CHARS:
        raise ProblemError(
            422,
            "draft_too_long",
            f"Your text is longer than {MAX_DRAFT_CHARS:,} characters. Shorten it to save it.",
            max_chars=MAX_DRAFT_CHARS,
        )
    try:
        attempt = await practice.get_attempt(db, attempt_id)
    except ProblemError:
        raise _not_found() from None
    if attempt.mode is not Step.DICTATION:
        raise _not_found()
    await practice.require_step(db, attempt.session_id, Step.DICTATION)
    if attempt.status is not AttemptStatus.ACTIVE:
        raise ProblemError(409, "attempt_closed", "This attempt has already ended.")
    saved = await repository.save_draft(db, attempt.id, text, base_version)
    if saved is not None:
        return _draft(saved)
    current = await repository.ensure_draft(db, attempt.id, attempt.user_id)
    if current.draft_text == text:
        # A resend of a save that already landed (its answer was lost): not a conflict.
        return _draft(current)
    raise ProblemError(
        409,
        "draft_conflict",
        "Your text was changed in another tab or browser since this page last saved it.",
        draft_text=current.draft_text,
        draft_version=current.draft_version,
        updated_at=current.updated_at.isoformat(),
    )
