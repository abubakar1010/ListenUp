"""The rules of one Blind listen, checked beat by beat (FR-BL-1, FR-BL-3; ADR 0007, 0024).

Blind is one unbroken listen: no pause, seek, rewind or speed change. The browser
cannot be trusted to enforce that, so while the passage plays it sends a heartbeat
every 5 s with its position and state, and the server judges each beat against its
own clock (System Design 9.2). `judge` is that judgement, a pure function, so every
rule is here and nowhere else (NFR-MNT-2).

The server's clock runs from an anchor: the position and time playback could start
from (the passage start when the attempt starts, or the resume point). The position
must keep in step with it. Waiting the player reports (`buffering_ms`: loading,
waiting for data, the resume's wait and count) pauses that clock, up to 20 s per
listen.

A beat is refused, and the attempt voided with a reason, when:

- the page is hidden (`left_page`): the learner left the screen;
- the position is outside the passage or moved backwards (`seek`);
- the position is more than 1.5 s ahead of the clock (`too_fast`). Measured from the
  anchor, so a client cannot gain 1.5 s on every beat;
- no beat arrived for more than 15 s while the player did not report an interruption
  (`missed_heartbeat`);
- the position fell more than 6 s behind the clock without reported waiting (a pause
  the player did not report: 5 s, D13's limit, plus 1 s for the beat's own trip), a
  device pause of 5 s or more, or a second interruption (`interrupted`).

Interruptions the learner did not cause get one resume per attempt (D13): a network
stall (the player reports it once a beat gets through again, or its waiting uses up
the 20 s allowance), or a device or OS pause under 5 s. The resume is automatic
(D18): the server sets the restart point 3 s before the stop, and the player carries
on 3 s after the audio is ready again. The server accepts that one backward step as
part of the resume, never as a seek. The resumed listen gets a fresh 20 s allowance.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

HEARTBEAT_INTERVAL_MS = 5_000
"""How often the player sends a beat."""
MAX_SILENCE_MS = 15_000
"""A gap between beats longer than this, without a reported interruption, voids."""
AHEAD_TOLERANCE_MS = 1_500
"""How far the position may run ahead of the server's clock (network and timer jitter)."""
LAG_TOLERANCE_MS = 6_000
"""How far the position may fall behind the clock without reported waiting."""
BACKWARD_TOLERANCE_MS = 250
"""Rounding between the player's clock and the beats; anything more is a seek back."""
END_TOLERANCE_MS = 1_000
"""The listen counts as complete this close to the passage's end; also its overrun."""
BUFFERING_BUDGET_MS = 20_000
"""Waiting allowed per listen before it counts as a network stall."""
DEVICE_PAUSE_LIMIT_MS = 5_000
"""A device or OS pause this long or longer ends the attempt (D13)."""
MAX_RESUMES = 1
"""Resumes per attempt after an interruption the learner did not cause (D13)."""
RESUME_REWIND_MS = 3_000
"""The resume restarts this far before the stop (D18)."""
RESUME_DELAY_MS = 3_000
"""The resume starts this long after the audio is ready again (D18)."""
MEDIA_GRACE_MS = 60_000
"""The attempt's media URL works for the rest of the passage plus this (#62)."""


class PlayerState(StrEnum):
    """What the player says it is doing when it sends a beat."""

    PLAYING = "playing"
    BUFFERING = "buffering"
    """Loading or waiting for data."""
    INTERRUPTED = "interrupted"
    """Stopped by something the learner did not cause; `position_ms` is the stop."""
    RESUMING = "resuming"
    """After a granted resume: waiting for the audio, then the 3 s count."""
    ENDED = "ended"
    """Reached the end of the passage."""


class Interruption(StrEnum):
    NETWORK = "network"
    DEVICE = "device"


class VoidReason(StrEnum):
    LEFT_PAGE = "left_page"
    RELOAD = "reload"
    SEEK = "seek"
    MISSED_HEARTBEAT = "missed_heartbeat"
    TOO_FAST = "too_fast"
    INTERRUPTED = "interrupted"


CLIENT_VOID_REASONS = (VoidReason.LEFT_PAGE, VoidReason.RELOAD, VoidReason.SEEK)
"""Reasons the browser reports itself: leaving, reloading, or a seek it noticed."""


@dataclass(frozen=True)
class Beat:
    position_ms: int
    """The player's position in the clip (not in the passage)."""
    state: PlayerState
    visible: bool = True
    buffering_ms: int = 0
    """Time the audio waited since the last beat the server accepted, as the player
    measured it: loading, waiting for data, or the resume's wait and count."""
    interruption: Interruption | None = None
    interruption_ms: int = 0
    """How long a device pause lasted, as the player measured it."""


@dataclass(frozen=True)
class Listen:
    """The server's record of one attempt's playback (practice.blind_attempts)."""

    passage_start_ms: int
    passage_end_ms: int
    last_position_ms: int
    last_heartbeat_at: datetime
    anchor_position_ms: int
    """The position the clock runs from: the passage start, or the resume point."""
    anchor_at: datetime
    """When playback from `anchor_position_ms` could have started at the earliest,
    moved later by every wait the player reported."""
    buffering_ms: int = 0
    resume_count: int = 0
    resume_stop_ms: int | None = None
    """Where the interruption that used the resume stopped playback."""

    @classmethod
    def start(cls, passage_start_ms: int, passage_end_ms: int, now: datetime) -> "Listen":
        return cls(
            passage_start_ms=passage_start_ms,
            passage_end_ms=passage_end_ms,
            last_position_ms=passage_start_ms,
            last_heartbeat_at=now,
            anchor_position_ms=passage_start_ms,
            anchor_at=now,
        )

    @property
    def complete(self) -> bool:
        """The whole passage has played: the gist may be written (#65)."""
        return self.last_position_ms >= self.passage_end_ms - END_TOLERANCE_MS

    def media_deadline(self) -> datetime:
        """When the attempt's media URL stops working: the rest of the passage by the
        clock, the waiting still allowed, and a grace period (#62)."""
        rest = self.passage_end_ms - self.anchor_position_ms
        waiting = BUFFERING_BUDGET_MS - self.buffering_ms
        return self.anchor_at + timedelta(milliseconds=rest + waiting + MEDIA_GRACE_MS)

    def expected_position_ms(self, now: datetime) -> int:
        """Where playback should be at `now` by the server's clock."""
        return self.anchor_position_ms + _ms(now - self.anchor_at)


class Action(StrEnum):
    CONTINUE = "continue"
    RESUME = "resume"
    STOP = "stop"


@dataclass(frozen=True)
class Verdict:
    action: Action
    listen: Listen
    void_reason: VoidReason | None = None
    resume_from_ms: int | None = None

    @property
    def voided(self) -> bool:
        return self.void_reason is not None


def _ms(delta: timedelta) -> int:
    return int(delta.total_seconds() * 1000)


def _void(listen: Listen, reason: VoidReason) -> Verdict:
    return Verdict(Action.STOP, listen, void_reason=reason)


def judge(listen: Listen, beat: Beat, now: datetime) -> Verdict:
    """Accept a beat, grant the one resume, or void the attempt with a reason."""
    if not beat.visible:
        return _void(listen, VoidReason.LEFT_PAGE)
    if not (
        listen.passage_start_ms - BACKWARD_TOLERANCE_MS
        <= beat.position_ms
        <= listen.passage_end_ms + END_TOLERANCE_MS
    ):
        return _void(listen, VoidReason.SEEK)
    if beat.position_ms < listen.last_position_ms - BACKWARD_TOLERANCE_MS:
        return _void(listen, VoidReason.SEEK)
    if listen.complete:
        return Verdict(Action.CONTINUE, listen)  # the listen is over; late beats change nothing

    elapsed = max(0, _ms(now - listen.last_heartbeat_at))
    if beat.state is PlayerState.INTERRUPTED:
        if beat.position_ms > listen.expected_position_ms(now) + AHEAD_TOLERANCE_MS:
            return _void(listen, VoidReason.TOO_FAST)
        if (
            beat.interruption is Interruption.DEVICE
            and beat.interruption_ms >= DEVICE_PAUSE_LIMIT_MS
        ):
            return _void(listen, VoidReason.INTERRUPTED)
        return resume(listen, beat.position_ms, now)
    if elapsed > MAX_SILENCE_MS:
        return _void(listen, VoidReason.MISSED_HEARTBEAT)
    if beat.state is PlayerState.RESUMING and listen.resume_count == 0:
        return _void(listen, VoidReason.INTERRUPTED)

    waited = min(max(0, beat.buffering_ms), elapsed)
    if listen.buffering_ms + waited > BUFFERING_BUDGET_MS:
        return resume(listen, beat.position_ms, now)  # waiting this long is a stall
    paused = replace(
        listen,
        anchor_at=listen.anchor_at + timedelta(milliseconds=waited),
        buffering_ms=listen.buffering_ms + waited,
    )
    expected = paused.expected_position_ms(now)
    if beat.position_ms > expected + AHEAD_TOLERANCE_MS:
        return _void(listen, VoidReason.TOO_FAST)
    if beat.position_ms < expected - LAG_TOLERANCE_MS:
        return _void(listen, VoidReason.INTERRUPTED)
    return Verdict(
        Action.CONTINUE,
        replace(
            paused,
            last_position_ms=max(listen.last_position_ms, beat.position_ms),
            last_heartbeat_at=now,
        ),
    )


def resume(listen: Listen, stop_ms: int, now: datetime) -> Verdict:
    """The one resume after an interruption the learner did not cause (D13, D18).

    Restarts 3 s before the stop (or at the passage start) on a clock that starts now,
    with a fresh waiting allowance; a second interruption voids the attempt.
    """
    if listen.resume_count >= MAX_RESUMES:
        return _void(listen, VoidReason.INTERRUPTED)
    resume_from = max(listen.passage_start_ms, stop_ms - RESUME_REWIND_MS)
    resumed = replace(
        listen,
        last_position_ms=resume_from,
        last_heartbeat_at=now,
        anchor_position_ms=resume_from,
        anchor_at=now,
        buffering_ms=0,
        resume_count=listen.resume_count + 1,
        resume_stop_ms=stop_ms,
    )
    return Verdict(Action.RESUME, resumed, resume_from_ms=resume_from)


def client_void(listen: Listen, reason: VoidReason) -> VoidReason | None:
    """The reason to void with when the browser reports leaving, a reload or a seek.

    None once the passage has played to the end: leaving the gist form is safe.
    """
    if reason not in CLIENT_VOID_REASONS:
        raise ValueError(f"the browser cannot report {reason}")
    return None if listen.complete else reason


def heard_whole_passage(listen: Listen, now: datetime) -> bool:
    """The gist may be submitted: the position reached the end and enough server time
    has passed since the anchor to hear the rest of it (#65)."""
    if not listen.complete:
        return False
    end = listen.passage_end_ms - END_TOLERANCE_MS
    return listen.expected_position_ms(now) + AHEAD_TOLERANCE_MS >= end
