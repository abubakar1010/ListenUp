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
    round: int
    transcript_shown: bool
    playback_status: Literal["ready", "ended"]
    recorded_at: datetime | None


class Rounds(BaseModel):
    segment: Segment
    current: Round | None
    rounds: list[Round]
    text: str | None = None
