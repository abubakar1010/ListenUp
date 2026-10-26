"""Connected-speech forms, with no definition or translation (FR-CA-3)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NewCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mark_id: uuid.UUID
    written_form: str = Field(min_length=1, max_length=100)
    heard_form: str = Field(min_length=1, max_length=100)


class Card(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    slot: int
    mark_id: uuid.UUID | None
    written_form: str
    heard_form: str
    at_ms: int
    content_id: uuid.UUID
    audio_status: Literal["pending", "ready", "failed", "unavailable"]
    source_url: str
    created_at: datetime


class CardList(BaseModel):
    cards: list[Card]
    next_cursor: str | None
    remaining: int | None = None
