"""How much new audio a learner may add in a day (#41, D16, FR-CI-3; ADR 0027).

Pure rules, no I/O. The service reads the day's count and the learner's clips still
being prepared, and asks `allows` before an upload starts and again when it is
confirmed; the conversion job adds `counted_seconds` of each clip it makes playable.

- **What counts.** A clip counts with its length, but with at most 15 minutes, the
  longest passage a learner can practise (C2). A long clip stays usable: what costs
  shared compute is the passage that gets transcribed and profiled, never more than
  15 minutes of it per plan. Duplicates, failed files and anything never converted
  count nothing.
- **Clips still being prepared** have no known length yet, so each reserves the most a
  clip can count. A learner can therefore never queue more than a day's allowance at
  once.
- **The rule.** A new clip is allowed while the day's count plus the reserved minutes is
  under the limit. The clip that crosses the limit is let in whole, so a day can end at
  most 15 minutes over it; refusing a clip only for its last minutes would make the
  learner cut files to fit a number they cannot see in advance.
- **The day** is the UTC day. The server stores no time zone for a learner, and a time
  zone sent by the browser could be changed to start a new day at will. The web app
  shows the reset time in the learner's own time.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# C2: a passage is 30 s to 15 min.
MAX_COUNTED_SECONDS = 15 * 60
DAY = timedelta(days=1)


def counted_seconds(duration_ms: int) -> int:
    """What one playable clip counts towards the day: its length to the nearest second,
    at most 15 minutes."""
    return min(MAX_COUNTED_SECONDS, round(max(0, duration_ms) / 1000))


def day_start(now: datetime) -> datetime:
    """Midnight UTC at the start of `now`'s day."""
    utc = now.astimezone(UTC)
    return datetime(utc.year, utc.month, utc.day, tzinfo=UTC)


def resets_at(now: datetime) -> datetime:
    """When the day's count starts again from zero: the next midnight UTC."""
    return day_start(now) + DAY


@dataclass(frozen=True)
class DailyAudio:
    used_seconds: int  # counted today by clips made playable
    clips_in_progress: int  # confirmed clips not converted yet, each reserving 15 minutes
    limit_seconds: int
    resets_at: datetime

    @property
    def reserved_seconds(self) -> int:
        return self.clips_in_progress * MAX_COUNTED_SECONDS

    @property
    def allows_more(self) -> bool:
        """Whether another clip may be added now."""
        return self.used_seconds + self.reserved_seconds < self.limit_seconds


def refusal_message(daily: DailyAudio, now: datetime) -> str:
    """Why a new clip is refused, and when the learner can add one."""
    limit = _minutes(daily.limit_seconds)
    wait = _wait(daily.resets_at - now)
    if daily.used_seconds >= daily.limit_seconds:
        return (
            f"You have added {limit} of new audio today, the daily limit. "
            f"You can add more after midnight UTC, in {wait}."
        )
    return (
        f"The clips you are adding now may use the rest of today's {limit} of new audio. "
        f"Add this one when they are ready, or after midnight UTC, in {wait}."
    )


def _minutes(seconds: int) -> str:
    minutes = seconds // 60
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def _wait(left: timedelta) -> str:
    minutes = max(1, math.ceil(left.total_seconds() / 60))
    if minutes < 60:
        return _minutes(minutes * 60)
    hours, rest = divmod(minutes, 60)
    hours_text = "1 hour" if hours == 1 else f"{hours} hours"
    return hours_text if rest == 0 else f"{hours_text} {_minutes(rest * 60)}"
