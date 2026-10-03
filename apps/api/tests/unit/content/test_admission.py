"""The daily allowance of new audio (#41, D16; ADR 0027)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from listenup.modules.content.domain.admission import (
    MAX_COUNTED_SECONDS,
    DailyAudio,
    counted_seconds,
    day_start,
    refusal_message,
    resets_at,
)

LIMIT = 120 * 60
NOW = datetime(2026, 10, 3, 18, 30, tzinfo=UTC)


def daily(used: int, in_progress: int = 0) -> DailyAudio:
    return DailyAudio(used, in_progress, LIMIT, resets_at(NOW))


@pytest.mark.parametrize(
    ("duration_ms", "counted"),
    [
        (30_000, 30),
        (35_400, 35),  # to the nearest second
        (35_600, 36),
        (14 * 60_000, 14 * 60),
        (15 * 60_000, 15 * 60),
        (15 * 60_000 + 1, 15 * 60),  # never more than the longest passage
        (3 * 60 * 60_000, 15 * 60),  # a three-hour clip stays usable
    ],
)
def test_a_clip_counts_its_length_up_to_the_longest_passage(duration_ms: int, counted: int) -> None:
    assert counted_seconds(duration_ms) == counted


def test_the_day_is_the_utc_day() -> None:
    assert day_start(NOW) == datetime(2026, 10, 3, tzinfo=UTC)
    assert resets_at(NOW) == datetime(2026, 10, 4, tzinfo=UTC)
    # 03:00 in Dhaka (UTC+6) on 4 October is still 3 October in UTC.
    dhaka = datetime(2026, 10, 4, 3, 0, tzinfo=timezone(timedelta(hours=6)))
    assert resets_at(dhaka) == datetime(2026, 10, 4, tzinfo=UTC)
    # At midnight exactly a new day starts.
    assert resets_at(datetime(2026, 10, 4, tzinfo=UTC)) == datetime(2026, 10, 5, tzinfo=UTC)


def test_a_clip_is_allowed_while_the_day_is_under_the_limit() -> None:
    assert daily(0).allows_more
    assert daily(LIMIT - 1).allows_more  # the clip that crosses the limit is let in whole


def test_at_or_over_the_limit_no_clip_is_allowed() -> None:
    assert not daily(LIMIT).allows_more
    assert not daily(LIMIT + 14 * 60).allows_more


def test_clips_in_progress_reserve_the_most_a_clip_can_count() -> None:
    assert daily(0, in_progress=7).reserved_seconds == 7 * MAX_COUNTED_SECONDS
    assert daily(0, in_progress=7).allows_more  # 105 of 120 minutes reserved
    assert not daily(0, in_progress=8).allows_more  # 120 reserved
    assert not daily(LIMIT - 60, in_progress=1).allows_more


def test_the_message_says_when_the_limit_resets() -> None:
    message = refusal_message(daily(LIMIT), NOW)
    assert message == (
        "You have added 120 minutes of new audio today, the daily limit. "
        "You can add more after midnight UTC, in 5 hours 30 minutes."
    )


def test_the_message_points_at_clips_in_progress_when_they_hold_the_rest() -> None:
    message = refusal_message(daily(60 * 60, in_progress=4), NOW)
    assert message.startswith("The clips you are adding now may use the rest of today's 120")
    assert message.endswith(
        "Add this one when they are ready, or after midnight UTC, in 5 hours 30 minutes."
    )


@pytest.mark.parametrize(
    ("left", "text"),
    [
        (timedelta(seconds=20), "in 1 minute."),
        (timedelta(minutes=45), "in 45 minutes."),
        (timedelta(hours=1), "in 1 hour."),
        (timedelta(hours=23, minutes=59, seconds=1), "in 24 hours."),
    ],
)
def test_the_wait_is_in_whole_minutes_rounded_up(left: timedelta, text: str) -> None:
    reset = datetime(2026, 10, 4, tzinfo=UTC)
    message = refusal_message(DailyAudio(LIMIT, 0, LIMIT, reset), reset - left)
    assert message.endswith(text)
