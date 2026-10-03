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


class DailyAudio(BaseModel):
    """Today's allowance of new audio (D16). Days are UTC days."""

    used_seconds: int = Field(description="Counted today: each clip with at most 15 minutes")
    limit_seconds: int
    clips_in_progress: int = Field(description="Clips not prepared yet, queued or running")
    reserved_seconds: int = Field(description="Held for the clips in progress, 15 minutes each")
    can_add: bool = Field(description="Whether a new clip is accepted now")
    resets_at: datetime = Field(description="When the count starts again (midnight UTC)")


class StorageUse(BaseModel):
    used_bytes: int
    quota_bytes: int
    max_file_bytes: int
    daily_audio: DailyAudio


class ConfirmUpload(BaseModel):
    """Add an uploaded file to the library. YouTube links (#37) will be another shape."""

    upload_id: uuid.UUID
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LENGTH,
        description="Defaults to the file name without its extension",
    )
    keep_video: bool = Field(
        default=False,
        description="Keep the picture of a video (H.264 360p); otherwise only the sound is kept",
    )


ContentSource = Literal["upload", "youtube"]
MediaStatus = Literal["pending", "downloading", "playable", "failed", "expired"]
IntakeStage = Literal["queued", "waiting", "downloading", "checking", "converting", "saving"]


class ContentItem(BaseModel):
    id: uuid.UUID
    title: str
    source: ContentSource
    status: MediaStatus
    duration_ms: int | None
    created_at: datetime
    stage: IntakeStage | None = Field(
        default=None,
        description=(
            "Where an item still being prepared is: `queued` in the learner's own queue "
            "(two of their clips are prepared at a time), `waiting` for a free worker, then "
            "the job's own stages. Null once prepared or failed"
        ),
    )
    queue_position: int | None = Field(
        default=None,
        description="For a `queued` item: 1 when it is the next of the learner's clips to start",
    )


class ContentList(BaseModel):
    items: list[ContentItem]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page")


class ContentDetail(ContentItem):
    """One item, with what its page needs to show and play it."""

    media_object_id: uuid.UUID
    has_video: bool = Field(description="The playback file has a picture (only with keep_video)")
    keep_video: bool
    error_code: str | None = Field(description="Why processing failed; null unless failed")
    error_detail: str | None = Field(description="The reason, as the learner reads it")
    media_url: str | None = Field(
        description="Play from here (redirects to a signed URL); null until playable"
    )
    peaks_url: str | None = Field(
        description="Waveform peaks JSON (redirects to a signed URL); null until playable"
    )
