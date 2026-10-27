"""Learner-facing sentence lines and marks; all timings are absolute media milliseconds."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from listenup.modules.review.domain import MARK_TAGS, MarkTag


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


_TAG_VALUES = (
    f"One of {', '.join(MARK_TAGS)}, or null for no tag; "
    "any other value is refused with `mark_tag_invalid`."
)


class NewMark(BaseModel):
    """A mark the learner just made. The browser names it, so a resend is harmless."""

    id: uuid.UUID
    word_from: int = Field(ge=0, le=2**31 - 1)
    word_to: int = Field(ge=0, le=2**31 - 1)
    note: str | None = None
    tag: str | None = Field(default=None, description=_TAG_VALUES)


class MarkNote(BaseModel):
    note: str | None


class MarkStatus(BaseModel):
    """FR-TR-3: a suggested Dictation mark is confirmed; it never goes back to suggested."""

    status: Literal["confirmed"]


class MarkTagChange(BaseModel):
    """FR-TR-4: the mark's optional tag. Checked by the service so a refusal has its code."""

    tag: str | None = Field(description=_TAG_VALUES)


class Mark(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    word_from: int
    word_to: int
    at_ms: int  # absolute media time of the first word
    note: str | None
    source: Literal["dictation", "manual"]
    status: Literal["suggested", "confirmed"]
    tag: MarkTag | None
    created_at: datetime


class MarkList(BaseModel):
    marks: list[Mark]


class SavedMark(Mark):
    content_id: uuid.UUID
    source_url: str


class SavedMarkList(BaseModel):
    marks: list[SavedMark]
    next_cursor: str | None
