"""Absolute media times for a Shadow segment."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SegmentChoice(BaseModel):
    start_ms: int = Field(strict=True, ge=0, le=2**31 - 1)
    end_ms: int = Field(strict=True, ge=0, le=2**31 - 1)


class Segment(SegmentChoice):
    session_id: uuid.UUID
    chosen_by: Literal["system", "learner"]
    mark_count: int
    locked_at: datetime | None


class Round(BaseModel):
    id: uuid.UUID
    round: int
    transcript_shown: bool
    playback_status: Literal["ready", "ended"]
    recorded_at: datetime | None
    recording_available: bool
    # Grading is not built yet (ADR 0050): a saved recording shows no feedback.
    feedback: Literal["unavailable"] | None


class Rounds(BaseModel):
    segment: Segment
    current: Round | None
    rounds: list[Round]
    text: str | None = None


class RecordingRequest(BaseModel):
    mime: str = Field(max_length=100)
    size_bytes: int = Field(strict=True)


class RecordingTarget(BaseModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


class RecordingUpload(BaseModel):
    round_id: uuid.UUID
    upload: RecordingTarget
