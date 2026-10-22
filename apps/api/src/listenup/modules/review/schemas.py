"""Learner-facing sentence lines and marks; all timings are absolute media milliseconds."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TranscriptPassage(BaseModel):
    start_ms: int
    end_ms: int


class TranscriptWord(BaseModel):
    index: int
    text: str
    start_ms: int
    end_ms: int
    edited: bool = False


class TranscriptLine(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    words: list[TranscriptWord]


class TranscriptReview(BaseModel):
    session_id: uuid.UUID
    passage: TranscriptPassage
    media_url: str
    lines: list[TranscriptLine]


class NewMark(BaseModel):
    """A mark the learner just made. The browser names it, so a resend is harmless."""

    id: uuid.UUID
    word_from: int = Field(ge=0, le=2**31 - 1)
    word_to: int = Field(ge=0, le=2**31 - 1)
    note: str | None = None


class MarkNote(BaseModel):
    note: str | None


class Mark(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    word_from: int
    word_to: int
    at_ms: int  # absolute media time of the first word
    note: str | None
    source: Literal["dictation", "manual"]
    status: Literal["suggested", "confirmed"]
    created_at: datetime


class MarkList(BaseModel):
    marks: list[Mark]
