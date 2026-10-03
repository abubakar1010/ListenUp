"""Request and response models of the content module's routes."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from listenup.modules.content.domain.files import MAX_FILENAME_LENGTH, MAX_TITLE_LENGTH


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=MAX_FILENAME_LENGTH)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0, description="The file's exact size; storage refuses any other")


class UploadTarget(BaseModel):
    """Where and how the browser sends the file: one PUT with exactly these headers."""

    upload_id: uuid.UUID
    url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expires_at: datetime = Field(description="The upload must start before this time")


class StorageUse(BaseModel):
    used_bytes: int
    quota_bytes: int
    max_file_bytes: int


class ConfirmUpload(BaseModel):
    """Add an uploaded file to the library. YouTube links (#37) will be another shape."""

    upload_id: uuid.UUID
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LENGTH,
        description="Defaults to the file name without its extension",
    )


ContentSource = Literal["upload", "youtube"]
MediaStatus = Literal["pending", "downloading", "playable", "failed", "expired"]


class ContentItem(BaseModel):
    id: uuid.UUID
    title: str
    source: ContentSource
    status: MediaStatus
    duration_ms: int | None
    created_at: datetime


class ContentList(BaseModel):
    items: list[ContentItem]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page")
