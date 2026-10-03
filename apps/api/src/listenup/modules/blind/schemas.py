"""Request and response models of the Blind routes (Architecture 9.2: Blind)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from listenup.modules.blind.domain import Action, Interruption, PlayerState, VoidReason
from listenup.modules.practice.service import AttemptStatus, Step, StepStatus


class BlindAttempt(BaseModel):
    """One try at the Blind step. Positions are in the clip, in milliseconds."""

    id: uuid.UUID
    session_id: uuid.UUID
    status: AttemptStatus
    void_reason: VoidReason | None = Field(description="Why the attempt ended, when voided")
    started_at: datetime
    finished_at: datetime | None
    passage_start_ms: int
    passage_end_ms: int
    position_ms: int = Field(description="The last position the server accepted")
    resume_count: int = Field(description="0 or 1: the one resume after an interruption (D13)")
    resume_stop_ms: int | None = Field(description="Where the interruption that resumed stopped")
    listen_complete: bool = Field(description="The whole passage has played: write the gist")
    gist_text: str | None


class BlindStep(BaseModel):
    session_id: uuid.UUID
    passage_start_ms: int
    passage_end_ms: int
    step_status: StepStatus
    attempt: BlindAttempt | None = Field(description="The newest attempt, live or ended")


class StartedAttempt(BaseModel):
    attempt: BlindAttempt
    media_url: str = Field(
        description="The passage's audio for this attempt only; it stops working shortly "
        "after the passage's length"
    )
    heartbeat_interval_ms: int
    resume_delay_ms: int = Field(description="The wait before playback carries on (D18)")


class HeartbeatIn(BaseModel):
    position_ms: int = Field(ge=0, description="The player's position in the clip")
    state: PlayerState
    visible: bool = Field(default=True, description="The page is visible (not hidden)")
    buffering_ms: int = Field(
        default=0, ge=0, le=3_600_000, description="Time spent waiting for data since the last beat"
    )
    interruption: Interruption | None = Field(
        default=None, description="With `interrupted`: a network stall or a device pause"
    )
    interruption_ms: int = Field(
        default=0, ge=0, le=3_600_000, description="How long a device pause lasted"
    )


class HeartbeatOut(BaseModel):
    action: Action = Field(
        description="`continue`; `resume`: carry on from `resume_from_ms` after "
        "`resume_delay_ms` once the audio is ready; `stop`: the attempt has ended"
    )
    attempt: BlindAttempt
    resume_from_ms: int | None
    resume_delay_ms: int


class VoidIn(BaseModel):
    reason: Literal["left_page", "reload", "seek"]


class GistIn(BaseModel):
    text: str = Field(max_length=20_000, description="Three sentences or more")


class GistSubmitted(BaseModel):
    attempt: BlindAttempt
    open_step: Step | None = Field(description="The step that opened next")
    session_version: int
