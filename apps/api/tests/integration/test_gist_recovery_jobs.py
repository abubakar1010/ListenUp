"""Failure settlement, delayed work and late results against PostgreSQL."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from listenup.ai.errors import AIUnavailable
from listenup.ai.ports import Role
from listenup.ai.providers import fake
from listenup.modules.grading import jobs
from listenup.platform import jobs as platform_jobs
from listenup.platform.jobs import JobDeps, PermanentError, Reschedule, run_handler
from tests.integration.test_gist_grading_jobs import REPLAYS, stored
from tests.integration.test_gist_grading_jobs import ai as ai
from tests.integration.test_gist_grading_jobs import clip as clip
from tests.integration.test_gist_grading_jobs import database as database
from tests.integration.test_gist_grading_jobs import submit as submit

pytestmark = pytest.mark.anyio


async def test_late_success_overwrites_unavailable_once(
    submit, database, migrated_url, learner, ai
):
    case = json.loads((REPLAYS / "clean.json").read_text())
    attempt = await submit(case["gist"])
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET status='unavailable' WHERE attempt_id=%s", [attempt]
        )
    fake.register_text_response("grade_gist", case["response"])
    deps = JobDeps(database, None, 1)
    await jobs.grade_gist(deps, str(attempt), str(learner))
    await jobs.grade_gist(deps, str(attempt), str(learner))
    assert stored(migrated_url, attempt)[:3] == ("ready", 98, "excellent")
    assert len(ai) == 1


@pytest.mark.parametrize("timeout", [False, True])
async def test_exhausted_failure_and_timeout_set_unavailable(
    submit, database, migrated_url, learner, ai, monkeypatch, timeout
):
    attempt = await submit(json.loads((REPLAYS / "clean.json").read_text())["gist"])

    async def fail(*args, **kwargs):
        if timeout:
            await asyncio.Event().wait()
        raise AIUnavailable(Role.TEXT_AI, "provider down")

    monkeypatch.setattr(jobs.text_tasks, "run_task", fail)
    entry = platform_jobs._registry[jobs.GRADE_GIST_JOB]
    monkeypatch.setitem(
        platform_jobs._registry,
        jobs.GRADE_GIST_JOB,
        replace(entry, spec=replace(entry.spec, timeout=timedelta(milliseconds=20))),
    )
    with pytest.raises((AIUnavailable, TimeoutError)):
        await run_handler(
            jobs.GRADE_GIST_JOB,
            JobDeps(database, None, 4),
            attempt_id=str(attempt),
            user_id=str(learner),
        )
    assert stored(migrated_url, attempt)[0] == "unavailable"
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute(
            "SELECT gist_text FROM practice.blind_attempts WHERE attempt_id=%s", [attempt]
        ).fetchone()[0]


async def test_quota_wait_reschedules_and_recovers(
    submit, database, migrated_url, learner, ai, monkeypatch
):
    case = json.loads((REPLAYS / "clean.json").read_text())
    attempt = await submit(case["gist"])
    original = jobs.text_tasks.run_task

    async def quota(*args, **kwargs):
        raise AIUnavailable(Role.TEXT_AI, "quota_exhausted")

    monkeypatch.setattr(jobs.text_tasks, "run_task", quota)
    with pytest.raises(Reschedule) as caught:
        await jobs.grade_gist(JobDeps(database, None, 4), str(attempt), str(learner))
    assert caught.value.run_at > datetime.now(UTC)
    assert stored(migrated_url, attempt)[0] == "delayed"
    monkeypatch.setattr(jobs.text_tasks, "run_task", original)
    fake.register_text_response("grade_gist", case["response"])
    await jobs.grade_gist(JobDeps(database, None, 1), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "ready"


@pytest.mark.parametrize("failure", ["provider", "invalid", "timeout"])
@pytest.mark.parametrize("remaining_ms", [-1, 0, 1])
async def test_gist_quota_then_failure_uses_original_deadline(
    submit, database, migrated_url, learner, ai, monkeypatch, failure, remaining_ms
):
    from listenup.modules.blind import service as blind

    case = json.loads((REPLAYS / "clean.json").read_text())
    attempt = await submit(case["gist"])
    now = datetime.now(UTC)
    deadline = now + timedelta(milliseconds=remaining_ms)
    monkeypatch.setattr(jobs, "server_now", lambda: now)
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET feedback_deadline=%s WHERE attempt_id=%s",
            [deadline, attempt],
        )
        progress = conn.execute(
            "SELECT * FROM practice.session_steps ORDER BY session_id,position"
        ).fetchall()
    original = jobs.text_tasks.run_task

    async def quota(*args, **kwargs):
        raise AIUnavailable(Role.TEXT_AI, "quota_exhausted")

    monkeypatch.setattr(jobs.text_tasks, "run_task", quota)
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 1), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "delayed"

    async def fail(*args, **kwargs):
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure == "invalid":
            raise ValueError("invalid gist output")
        raise AIUnavailable(Role.TEXT_AI, "provider down")

    monkeypatch.setattr(jobs.text_tasks, "run_task", fail)
    entry = platform_jobs._registry[jobs.GRADE_GIST_JOB]
    if failure == "timeout":
        monkeypatch.setitem(
            platform_jobs._registry,
            entry.name,
            replace(entry, spec=replace(entry.spec, timeout=timedelta(milliseconds=100))),
        )
    error = {"provider": AIUnavailable, "invalid": ValueError, "timeout": TimeoutError}[failure]
    # A non-final failure must restore the UI deadline, not exhaust automatic work.
    with pytest.raises(error):
        await run_handler(
            entry.name,
            JobDeps(database, None, 2),
            attempt_id=str(attempt),
            user_id=str(learner),
        )
    assert stored(migrated_url, attempt)[0] == ("pending" if remaining_ms > 0 else "unavailable")
    async with database.transaction(learner) as db:
        await blind.retry_grade(db, learner, attempt, now)
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT feedback_deadline FROM grading.gist_grades WHERE attempt_id=%s", [attempt]
            ).fetchone()[0]
            == deadline
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM procrastinate.procrastinate_jobs "
                "WHERE queueing_lock=%s AND status IN ('todo','doing')",
                [f"gist-grade:{attempt}"],
            ).fetchone()[0]
            == 1
        )
    monkeypatch.setattr(jobs.text_tasks, "run_task", original)
    fake.register_text_response("grade_gist", case["response"])
    await jobs.grade_gist(JobDeps(database, None, 3), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[:3] == ("ready", 98, "excellent")
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT * FROM practice.session_steps ORDER BY session_id,position"
            ).fetchall()
            == progress
        )
        assert (
            conn.execute(
                "SELECT gist_text FROM practice.blind_attempts WHERE attempt_id=%s", [attempt]
            ).fetchone()[0]
            == case["gist"]
        )


@pytest.mark.parametrize("failure", ["provider", "invalid", "timeout", "permanent"])
async def test_reference_quota_then_exhaustion_can_retry_and_recover(
    submit, database, migrated_url, learner, ai, clip, monkeypatch, failure
):
    from listenup.modules.blind import service as blind

    case = json.loads((REPLAYS / "clean.json").read_text())
    attempt = await submit(case["gist"])
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM grading.key_points")
        conn.execute(
            "UPDATE grading.gist_grades SET feedback_deadline=%s WHERE attempt_id=%s",
            [datetime.now(UTC) - timedelta(seconds=1), attempt],
        )
        progress = conn.execute(
            "SELECT * FROM practice.session_steps ORDER BY session_id,position"
        ).fetchall()
    original = jobs.text_tasks.run_task

    async def quota(*args, **kwargs):
        raise AIUnavailable(Role.TEXT_AI, "quota_exhausted")

    monkeypatch.setattr(jobs.text_tasks, "run_task", quota)
    with pytest.raises(Reschedule):
        await jobs.extract_key_points(JobDeps(database, None, 1), str(clip[0]), 0, 120000)
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 1), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "delayed"

    async def fail(*args, **kwargs):
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure == "invalid":
            raise ValueError("invalid reference output")
        if failure == "permanent":
            raise PermanentError("invalid reference input")
        raise AIUnavailable(Role.TEXT_AI, "provider down")

    monkeypatch.setattr(jobs.text_tasks, "run_task", fail)
    entry = platform_jobs._registry[jobs.service.EXTRACT_KEY_POINTS]
    if failure == "timeout":
        monkeypatch.setitem(
            platform_jobs._registry,
            entry.name,
            replace(entry, spec=replace(entry.spec, timeout=timedelta(milliseconds=100))),
        )
    error_type = {
        "provider": AIUnavailable,
        "invalid": ValueError,
        "timeout": TimeoutError,
        "permanent": PermanentError,
    }[failure]
    with pytest.raises(error_type):
        await run_handler(
            entry.name,
            JobDeps(database, None, 4),
            media_id=str(clip[0]),
            start_ms=0,
            end_ms=120000,
        )
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM grading.key_point_delays WHERE media_object_id=%s", [clip[0]]
            ).fetchone()[0]
            == 0
        )
        conn.execute(
            "UPDATE procrastinate.procrastinate_jobs SET status='failed' "
            "WHERE task_name=%s AND args->>'media_id'=%s",
            [entry.name, str(clip[0])],
        )
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 4), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "unavailable"
    async with database.transaction(learner) as db:
        await blind.retry_grade(db, learner, attempt, datetime.now(UTC))
    with psycopg.connect(migrated_url) as conn:
        for key in [f"gist-grade:{attempt}", f"key-points:{clip[0]}:0:120000"]:
            assert (
                conn.execute(
                    "SELECT count(*) FROM procrastinate.procrastinate_jobs "
                    "WHERE queueing_lock=%s AND status IN ('todo','doing')",
                    [key],
                ).fetchone()[0]
                == 1
            )
    monkeypatch.setattr(jobs.text_tasks, "run_task", original)
    await jobs.extract_key_points(JobDeps(database, None, 1), str(clip[0]), 0, 120000)
    fake.register_text_response("grade_gist", case["response"])
    await jobs.grade_gist(JobDeps(database, None, 1), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[:3] == ("ready", 98, "excellent")
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT * FROM practice.session_steps ORDER BY session_id,position"
            ).fetchall()
            == progress
        )


async def test_deadline_job_is_guarded_by_cycle_and_delayed_state(
    submit, database, migrated_url, learner, ai, monkeypatch
):
    from listenup.platform.clock import server_now

    case = json.loads((REPLAYS / "clean.json").read_text())
    attempt = await submit(case["gist"])
    now = server_now()
    old = now - timedelta(seconds=1)
    current = now + timedelta(seconds=30)
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET feedback_deadline=%s WHERE attempt_id=%s",
            [current, attempt],
        )
    deps = JobDeps(database, None, 1)
    await jobs.gist_deadline(deps, str(attempt), str(learner), old.isoformat())
    assert stored(migrated_url, attempt)[0] == "pending"
    with pytest.raises(Reschedule):
        await jobs.gist_deadline(deps, str(attempt), str(learner), current.isoformat())
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET feedback_deadline=%s, status='delayed' "
            "WHERE attempt_id=%s",
            [old, attempt],
        )
    await jobs.gist_deadline(deps, str(attempt), str(learner), old.isoformat())
    assert stored(migrated_url, attempt)[0] == "delayed"
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE grading.gist_grades SET status='pending' WHERE attempt_id=%s", [attempt]
        )
    await jobs.gist_deadline(deps, str(attempt), str(learner), old.isoformat())
    assert stored(migrated_url, attempt)[0] == "unavailable"


async def test_missing_key_points_wait_without_exhausting_grading(
    submit, database, migrated_url, learner, ai
):
    attempt = await submit(json.loads((REPLAYS / "clean.json").read_text())["gist"])
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM grading.key_points")
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 4), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "pending"


@pytest.mark.parametrize("remaining_ms", [-1, 0, 1])
async def test_cleared_reference_quota_uses_original_deadline(
    submit, database, migrated_url, learner, ai, monkeypatch, remaining_ms
):
    attempt = await submit(json.loads((REPLAYS / "clean.json").read_text())["gist"])
    now = datetime.now(UTC)
    monkeypatch.setattr(jobs, "server_now", lambda: now)
    deadline = now + timedelta(milliseconds=remaining_ms)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM grading.key_points")
        conn.execute(
            "UPDATE grading.gist_grades SET status='delayed', feedback_deadline=%s "
            "WHERE attempt_id=%s",
            [deadline, attempt],
        )
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 4), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == ("pending" if remaining_ms > 0 else "unavailable")
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT feedback_deadline FROM grading.gist_grades WHERE attempt_id=%s", [attempt]
            ).fetchone()[0]
            == deadline
        )


async def test_key_point_quota_wait_preserves_reference_work(
    database, migrated_url, clip, monkeypatch
):
    async def quota(*args, **kwargs):
        raise AIUnavailable(Role.TEXT_AI, "quota_exhausted")

    monkeypatch.setattr(jobs.text_tasks, "run_task", quota)
    with pytest.raises(Reschedule):
        await jobs.extract_key_points(JobDeps(database, None, 4), str(clip[0]), 0, 120000)


async def test_key_point_quota_is_visible_to_waiting_gist(
    submit, database, migrated_url, learner, ai, clip, monkeypatch
):
    attempt = await submit(json.loads((REPLAYS / "clean.json").read_text())["gist"])
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM grading.key_points")

    original = jobs.text_tasks.run_task

    async def quota(*args, **kwargs):
        raise AIUnavailable(Role.TEXT_AI, "quota_exhausted")

    monkeypatch.setattr(jobs.text_tasks, "run_task", quota)
    with pytest.raises(Reschedule):
        await jobs.extract_key_points(JobDeps(database, None, 4), str(clip[0]), 0, 120000)
    with pytest.raises(Reschedule):
        await jobs.grade_gist(JobDeps(database, None, 4), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "delayed"

    monkeypatch.setattr(jobs.text_tasks, "run_task", original)
    await jobs.extract_key_points(JobDeps(database, None, 1), str(clip[0]), 0, 120000)
    with psycopg.connect(migrated_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM grading.key_point_delays WHERE media_object_id=%s", [clip[0]]
            ).fetchone()[0]
            == 0
        )
    fake.register_text_response(
        "grade_gist", json.loads((REPLAYS / "clean.json").read_text())["response"]
    )
    await jobs.grade_gist(JobDeps(database, None, 1), str(attempt), str(learner))
    assert stored(migrated_url, attempt)[0] == "ready"
