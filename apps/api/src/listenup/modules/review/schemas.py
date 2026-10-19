"""Learner-facing sentence lines; all timings are absolute media milliseconds."""

import uuid

from pydantic import BaseModel


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
