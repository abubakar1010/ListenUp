"""Request and response models of the Dictation routes (Architecture 9.2: Dictation).

None of them has a field for reference text: Dictation hides the transcript
(FR-DI-3, FR-TX-5).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from listenup.modules.dictation.repository import DiffStatus, ScoringStatus
from listenup.modules.practice.service import AttemptStatus


class DictationPassage(BaseModel):
    """The part of the clip the player may play, in milliseconds, [start_ms, end_ms)."""

    start_ms: int
    end_ms: int


class DictationAttempt(BaseModel):
    """The learner's Dictation attempt with its saved draft (FR-DI-1, FR-DI-4)."""

    id: uuid.UUID
    session_id: uuid.UUID
    status: AttemptStatus
    started_at: datetime
    resumed: bool = Field(description="True when an attempt already in progress was resumed")
    draft_text: str
    draft_version: int = Field(description="Send it back with the next draft save")
    draft_updated_at: datetime
    passage: DictationPassage
    media_url: str = Field(
        description="The API path that redirects to the playback file (ADR 0022); "
        "play only `passage` of it"
    )


class SaveDraft(BaseModel):
    draft_text: str = Field(description="The whole text, at most 20,000 characters")
    draft_version: int = Field(ge=0, description="The `draft_version` this text was based on")


class SavedDraft(BaseModel):
    draft_version: int = Field(description="The new version; base the next save on it")
    updated_at: datetime


class SubmitDictation(BaseModel):
    text: str = Field(
        description="The whole text as the learner sees it, at most 20,000 characters"
    )
    version: int = Field(ge=0, description="The `version` of the session this page last saw")
    replay_count: int = Field(
        ge=0, le=100_000, description="How often the learner replayed the passage"
    )


class DictationSubmission(BaseModel):
    """The submission was accepted; the score follows (FR-DI-5, ADR 0042).

    Never carries the diff or any reference text, whatever the state of scoring.
    """

    attempt_id: uuid.UUID
    status: AttemptStatus
    scoring_status: ScoringStatus


class DiffItem(BaseModel):
    """One word of the diff, in passage order; extra words sit where they were typed."""

    index: int | None = Field(
        description="Position in the passage word sequence; null for an extra word"
    )
    status: DiffStatus
    word: str = Field(description="The reference word; empty for an extra word")
    typed: str = Field(description="What the learner typed for it; empty when missing")


class DiffCounts(BaseModel):
    correct: int
    spelling_slip: int
    wrong: int
    missing: int
    extra: int


class DictationResult(BaseModel):
    """The score. The only place the reference text appears, and only after scoring."""

    accuracy: float = Field(description="Percent with two decimals; spelling slips count")
    counts: DiffCounts
    items: list[DiffItem]


class DictationAttemptView(BaseModel):
    """The attempt after the draft stage: its state and, once scored, the result."""

    id: uuid.UUID
    session_id: uuid.UUID
    status: AttemptStatus
    scoring_status: ScoringStatus | None = Field(description="Null until the attempt is submitted")
    result: DictationResult | None = Field(description="Null until `scoring_status` is scored")
