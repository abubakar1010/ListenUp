"""Request and response models of the sessions routes (Architecture 9.2: Sessions)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from listenup.modules.practice.domain import Entry, SessionStatus, Step, StepStatus


class PassageRange(BaseModel):
    """The practised part of the clip in milliseconds, half-open [start_ms, end_ms) (C2)."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0, description="30 s to 15 min after start_ms, within the clip")


class StartSession(BaseModel):
    content_id: uuid.UUID
    passage: PassageRange
    entry: Entry = Field(description="Blind, Dictation or both (Blind first, OQ-1)")


class ChangeEntry(BaseModel):
    entry: Entry
    version: int = Field(ge=0, description="The session `version` the client last saw")


class SkipStep(BaseModel):
    confirmed: bool = Field(
        default=False, description="The learner confirmed the skip; without it, 422"
    )
    version: int = Field(ge=0, description="The session `version` the client last saw")


class SessionStep(BaseModel):
    step: Step
    position: int = Field(description="1-based place in the plan")
    status: StepStatus


class Session(BaseModel):
    """A practice session with its plan, for "Step N of M" (UI-1)."""

    id: uuid.UUID
    content_id: uuid.UUID
    content_title: str
    passage: PassageRange
    entry: Entry
    status: SessionStatus
    version: int = Field(description="Send it back with every change; a stale one gets 409")
    steps: list[SessionStep]
    step_count: int = Field(description="M in 'Step N of M': 4 or 5")
    open_step: Step | None = Field(description="The step the learner can work on; null if closed")
    open_position: int | None = Field(description="N in 'Step N of M'; null when closed")
    entry_locked: bool = Field(description="True once Transcript has opened (FR-PL-5)")
    entry_locked_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SessionList(BaseModel):
    items: list[Session]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page")
