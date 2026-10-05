"""Background jobs on four priority lanes (System Design 4; Architecture 3).

Feature modules declare jobs with `@job(Lane.X, "module.name")` and queue them with
`enqueue(session, "module.name", ...)` inside the transaction that changes the data,
so a job never runs for a change that was rolled back (System Design 4.2).

A job handler is `async def handler(deps: JobDeps, **args)`. It must be idempotent,
writing its results as upserts on a natural key, because a crashed or timed-out
attempt is run again (System Design 11.1, 11.3). Raise `PermanentError` for input
that can never succeed (validation errors), so the job fails at once instead of
retrying; anything else is retried with exponential backoff and jitter.

A job whose failure must leave a visible state (an item marked failed instead of
processing for ever) passes `on_give_up`: it runs after the last attempt fails, timeouts
included, outside the timeout, with the job's own arguments.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import procrastinate
from procrastinate.job_context import JobContext
from procrastinate.jobs import Job
from procrastinate.retry import BaseRetryStrategy, RetryDecision
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.log import current_request_id, request_id_bound

logger = logging.getLogger(__name__)


class Lane(StrEnum):
    SPEECH_INTERACTIVE = "speech-interactive"
    INTAKE = "intake"
    AI = "ai"
    BACKGROUND = "background"


@dataclass(frozen=True)
class LaneSpec:
    timeout: timedelta
    max_attempts: int
    # Within a worker that serves several lanes, higher runs first.
    priority: int


# System Design 4.1. Concurrency belongs to the worker pools (listenup.worker).
LANES: dict[Lane, LaneSpec] = {
    Lane.SPEECH_INTERACTIVE: LaneSpec(timedelta(minutes=3), 3, priority=30),
    Lane.INTAKE: LaneSpec(timedelta(minutes=10), 5, priority=20),
    Lane.AI: LaneSpec(timedelta(seconds=60), 4, priority=10),
    Lane.BACKGROUND: LaneSpec(timedelta(minutes=15), 5, priority=0),
}


class PermanentError(Exception):
    """The job can never succeed with these inputs; fail now without retrying."""


class Backoff(BaseRetryStrategy):
    """About 10 s, 40 s, 160 s ... between attempts, each varied by up to 20%.

    The jitter spreads out retries of jobs that failed together, for example when a
    provider was down for a minute.
    """

    def __init__(self, max_attempts: int, base_seconds: float = 10.0, factor: float = 4.0) -> None:
        self.max_attempts = max_attempts
        self.base_seconds = base_seconds
        self.factor = factor

    def delay(self, failed_attempts: int) -> float:
        wait = self.base_seconds * self.factor ** (failed_attempts - 1)
        return wait * random.uniform(0.8, 1.2)

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if isinstance(exception, PermanentError):
            return None
        # job.attempts counts the runs before this one.
        failed_attempts = job.attempts + 1
        if failed_attempts >= self.max_attempts:
            return None
        return RetryDecision(
            retry_at=datetime.now(UTC) + timedelta(seconds=self.delay(failed_attempts))
        )


@dataclass(frozen=True)
class JobDeps:
    """What a job handler gets besides its own arguments."""

    database: Database
    job_id: int | None
    attempt: int  # 1 for the first run


Handler = Callable[..., Awaitable[Any]]


class JobGate(Protocol):
    """Decides, before a job starts, whether it should wait instead (backpressure)."""

    async def should_wait(self, database: Database) -> bool: ...


@dataclass
class _Runtime:
    database: Database | None = None


_runtime = _Runtime()
_gates: dict[Lane, JobGate] = {}

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().database_url)
)

REQUEST_ID_ARG = "_request_id"
GATE_RETRY_SECONDS = 10


def configure_runtime(database: Database) -> None:
    """Called once by each worker process (and by tests) before jobs run."""
    _runtime.database = database


def set_gate(lane: Lane, gate: JobGate | None) -> None:
    if gate is None:
        _gates.pop(lane, None)
    else:
        _gates[lane] = gate


@dataclass(frozen=True)
class JobType:
    name: str
    lane: Lane
    spec: LaneSpec
    handler: Handler
    on_give_up: Handler | None = None
    schedule: str | None = None  # cron expression (UTC) for a job that runs on its own


_registry: dict[str, JobType] = {}
_scheduled: set[str] = set()


def job(
    lane: Lane,
    name: str,
    *,
    timeout: timedelta | None = None,
    max_attempts: int | None = None,
    on_give_up: Handler | None = None,
    schedule: str | None = None,
) -> Callable[[Handler], Handler]:
    """Register `handler` as job `name` on `lane`; see the module docstring for
    `on_give_up`.

    `schedule` (a cron expression in UTC) makes it a scheduled job as well: the worker
    pool that serves `lane` queues it at each tick (`install_schedules`), with a
    `timestamp` argument. Procrastinate records each tick it queued, so several
    processes serving the lane still queue a tick once.
    """
    base = LANES[lane]
    spec = LaneSpec(
        timeout or base.timeout,
        max_attempts or base.max_attempts,
        base.priority,
    )

    def register(handler: Handler) -> Handler:
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"job {name} must be async: CPU work runs in a subprocess")
        if name in _registry:
            raise ValueError(f"job {name} is already registered")

        async def run(context: JobContext, /, **args: Any) -> Any:
            request_id = args.pop(REQUEST_ID_ARG, None)
            database = _runtime.database
            if database is None:
                raise RuntimeError("configure_runtime() was not called in this worker")
            with request_id_bound(request_id):
                gate = _gates.get(lane)
                if gate is not None and await gate.should_wait(database):
                    await _postpone(database, context.job, args, request_id)
                    return None
                deps = JobDeps(database, context.job.id, context.job.attempts + 1)
                return await run_handler(name, deps, **args)

        app.task(
            name=name,
            queue=lane.value,
            priority=spec.priority,
            pass_context=True,
            retry=Backoff(spec.max_attempts, get_settings().job_retry_base_seconds),
        )(run)
        _registry[name] = JobType(name, lane, spec, handler, on_give_up, schedule)
        return handler

    return register


def install_schedules(lanes: Iterable[Lane]) -> list[str]:
    """Turn on the scheduled jobs of `lanes` in this process; returns their names.

    Only worker processes call this (`listenup.worker`), for the lanes they serve, so
    tests and the API never queue scheduled work on their own.
    """
    served = set(lanes)
    installed: list[str] = []
    for job_type in _registry.values():
        if job_type.schedule is None or job_type.lane not in served:
            continue
        if job_type.name not in _scheduled:
            app.periodic(cron=job_type.schedule, periodic_id=job_type.name)(
                app.tasks[job_type.name]
            )
            _scheduled.add(job_type.name)
        installed.append(job_type.name)
    return installed


async def run_handler(name: str, deps: JobDeps, /, **args: Any) -> Any:
    """Run job `name` as a worker does: under its timeout, and settled by its
    `on_give_up` when this was the last attempt.

    The timeout cancels the handler, so the handler itself never sees a timeout as an
    ordinary error; settling here, outside the timeout, covers it as well.
    """
    entry = _registry[name]
    try:
        async with asyncio.timeout(entry.spec.timeout.total_seconds()):
            return await entry.handler(deps, **args)
    except PermanentError:
        raise
    except Exception:
        if entry.on_give_up is not None and deps.attempt >= entry.spec.max_attempts:
            await entry.on_give_up(deps, **args)
        raise


async def enqueue(
    session: AsyncSession,
    name: str,
    *,
    unique_key: str | None = None,
    lock: str | None = None,
    run_at: datetime | None = None,
    **args: Any,
) -> int | None:
    """Queue job `name` in the caller's transaction; returns its id.

    `unique_key`: while a job with this key is waiting, queueing another is a no-op
    and returns None (for example 'grade_round:<round id>', so two clicks on retry
    queue one job). `lock`: jobs sharing a lock run one at a time, so identical work
    on one resource is never done twice in parallel.
    """
    job_type = _registry.get(name)
    if job_type is None:
        raise KeyError(f"unknown job {name!r}")
    payload = dict(args)
    if (request_id := current_request_id()) is not None:
        payload[REQUEST_ID_ARG] = request_id
    try:
        # A savepoint, so a duplicate key does not abort the caller's transaction.
        async with session.begin_nested():
            job_id: int | None = await session.scalar(
                text("""
                SELECT unnest(procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW(
                  :queue, :task, :priority, :lock, :unique_key, CAST(:args AS jsonb), :run_at
                )::procrastinate.procrastinate_job_to_defer_v1]))
                """),
                {
                    "queue": job_type.lane.value,
                    "task": name,
                    "priority": job_type.spec.priority,
                    "lock": lock,
                    "unique_key": unique_key,
                    "args": json.dumps(payload),
                    "run_at": run_at,
                },
            )
        return job_id
    except IntegrityError as error:
        if "procrastinate_jobs_queueing_lock_idx" in str(error.orig):
            return None
        raise


async def _postpone(
    database: Database, current: Job, args: dict[str, Any], request_id: str | None
) -> None:
    """Re-queue this job a little later instead of running it now.

    The current run then ends successfully, so waiting never uses up an attempt.
    """
    payload = dict(args)
    if request_id is not None:
        payload[REQUEST_ID_ARG] = request_id
    async with database.transaction() as session:
        await session.execute(
            text("""
            SELECT procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW(
              :queue, :task, :priority, :lock, :unique_key, CAST(:args AS jsonb),
              now() + make_interval(secs => :delay)
            )::procrastinate.procrastinate_job_to_defer_v1])
            """),
            {
                "queue": current.queue,
                "task": current.task_name,
                "priority": current.priority,
                "lock": current.lock,
                "unique_key": current.queueing_lock,
                "args": json.dumps(payload),
                "delay": GATE_RETRY_SECONDS,
            },
        )
    logger.info("job postponed by backpressure", extra={"job": current.task_name})


async def failed_jobs(session: AsyncSession, limit: int = 50) -> list[dict[str, Any]]:
    """Jobs that used up their attempts, newest first, for the admin view (11.1)."""
    rows = await session.execute(
        text("""
        SELECT j.id, j.queue_name AS lane, j.task_name AS name, j.attempts,
               j.args - :request_id_arg AS args, max(e.at) AS failed_at
          FROM procrastinate.procrastinate_jobs j
          LEFT JOIN procrastinate.procrastinate_events e
            ON e.job_id = j.id AND e.type = 'failed'
         WHERE j.status = 'failed'
         GROUP BY j.id
         ORDER BY failed_at DESC NULLS LAST, j.id DESC
         LIMIT :limit
        """),
        {"limit": limit, "request_id_arg": REQUEST_ID_ARG},
    )
    return [dict(row) for row in rows.mappings()]


class SpeechBacklogGate:
    """Backpressure for the media pool (System Design 4.2, 11.1).

    When a speech-interactive job (a learner waiting for Shadow feedback) has waited
    more than `threshold`, intake jobs stop starting; they resume once the
    speech-interactive lane has drained completely, so the pool does not flap
    between the two.
    """

    def __init__(self, threshold: timedelta = timedelta(seconds=30)) -> None:
        self.threshold = threshold
        self.paused = False

    async def should_wait(self, database: Database) -> bool:
        async with database.transaction() as session:
            waiting, oldest = (
                await session.execute(
                    text("""
                    SELECT count(*), extract(epoch FROM now() - min(coalesce(j.scheduled_at, e.at)))
                      FROM procrastinate.procrastinate_jobs j
                      JOIN procrastinate.procrastinate_events e
                        ON e.job_id = j.id AND e.type = 'deferred'
                     WHERE j.queue_name = :lane AND j.status = 'todo'
                       AND (j.scheduled_at IS NULL OR j.scheduled_at <= now())
                    """),
                    {"lane": Lane.SPEECH_INTERACTIVE.value},
                )
            ).one()
        if oldest is not None and float(oldest) > self.threshold.total_seconds():
            if not self.paused:
                logger.warning("intake paused: speech-interactive backlog")
            self.paused = True
        elif waiting == 0:
            if self.paused:
                logger.info("intake resumed: speech-interactive lane drained")
            self.paused = False
        return self.paused
