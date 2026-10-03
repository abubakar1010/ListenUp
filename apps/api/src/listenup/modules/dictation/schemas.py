"""Request and response models of the Dictation routes (Architecture 9.2: Dictation).

None of them has a field for reference text: Dictation hides the transcript
(FR-DI-3, FR-TX-5).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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
