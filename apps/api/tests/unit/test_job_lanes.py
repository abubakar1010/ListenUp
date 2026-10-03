"""Lane settings, backoff and worker pools (System Design 4.1, 4.2)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from procrastinate.jobs import Job

from listenup.platform.jobs import LANES, Backoff, Lane, PermanentError
from listenup.worker import POOLS, main


def fake_job(attempts: int) -> Job:
    return cast(Job, SimpleNamespace(attempts=attempts))


def seconds_until(decision: Any) -> float:
    retry_at: datetime = decision.retry_at
    return (retry_at - datetime.now(UTC)).total_seconds()


@pytest.mark.parametrize(("failed_before", "expected"), [(0, 10), (1, 40), (2, 160)])
def test_backoff_grows_four_times_with_up_to_20_percent_jitter(
    failed_before: int, expected: float
) -> None:
    waits = [
        seconds_until(
            Backoff(5).get_retry_decision(exception=OSError(), job=fake_job(failed_before))
        )
        for _ in range(50)
    ]
    assert all(expected * 0.79 <= w <= expected * 1.2 for w in waits)
    assert len({round(w, 3) for w in waits}) > 1  # jittered


def test_no_retry_after_the_last_attempt() -> None:
    assert Backoff(3).get_retry_decision(exception=OSError(), job=fake_job(2)) is None


def test_permanent_errors_are_not_retried() -> None:
    decision = Backoff(5).get_retry_decision(exception=PermanentError("bad"), job=fake_job(0))
    assert decision is None


def test_lane_limits_match_the_system_design() -> None:
    assert {lane: (spec.timeout, spec.max_attempts) for lane, spec in LANES.items()} == {
        Lane.SPEECH_INTERACTIVE: (timedelta(minutes=3), 3),
        Lane.INTAKE: (timedelta(minutes=10), 5),
        Lane.AI: (timedelta(seconds=60), 4),
        Lane.BACKGROUND: (timedelta(minutes=15), 5),
    }
    priorities = [LANES[lane].priority for lane in Lane]
    assert priorities == sorted(priorities, reverse=True)  # lane 1 first


def slots(pool: str, lane: Lane) -> int:
    return sum(spec.concurrency for spec in POOLS[pool] if lane in spec.lanes)


def test_media_pool_gives_speech_both_slots_and_intake_one() -> None:
    assert slots("media", Lane.SPEECH_INTERACTIVE) == 2
    assert slots("media", Lane.INTAKE) == 1
    assert slots("media", Lane.AI) == slots("media", Lane.BACKGROUND) == 0


def test_default_pool_runs_eight_ai_jobs_and_one_background_job() -> None:
    assert slots("default", Lane.AI) == 8
    assert slots("default", Lane.BACKGROUND) == 1
    assert slots("default", Lane.SPEECH_INTERACTIVE) == slots("default", Lane.INTAKE) == 0


def test_an_unknown_pool_is_refused() -> None:
    with pytest.raises(SystemExit, match="usage"):
        main(["everything"])
