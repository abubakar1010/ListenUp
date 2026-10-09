"""Worker pools: `python -m listenup.worker media` or `python -m listenup.worker default`.

Two processes so AI network waits never take CPU from speech work (System Design 4.1):

- media: lanes speech-interactive and intake on two slots. Speech-interactive may use
  both; intake at most one, and it pauses while learners wait for speech feedback.
- default: lane ai with 8 concurrent async jobs, lane background with 1.

Each process writes a ready file once its models are loaded; the container health
check looks for it, so traffic is not routed to a pool that cannot work yet.
"""

import asyncio
import contextlib
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from listenup.ai.gateway import get_gateway
from listenup.ai.ports import Role
from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.jobs import (
    Lane,
    SpeechBacklogGate,
    app,
    configure_runtime,
    install_schedules,
    sample_queue_forever,
    set_gate,
)
from listenup.platform.log import configure_logging
from listenup.platform.telemetry import configure_telemetry, shutdown_telemetry

logger = logging.getLogger(__name__)

READY_FILE = Path("/tmp/listenup-worker-ready")

# Modules whose job handlers this process registers. Each feature story adds its
# module's jobs package here.
JOB_MODULES: list[str] = [
    "listenup.modules.identity.jobs",
    "listenup.modules.content.jobs",
    "listenup.modules.export.jobs",
]


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    lanes: tuple[Lane, ...]
    concurrency: int


POOLS: dict[str, tuple[WorkerSpec, ...]] = {
    "media": (
        WorkerSpec("media-shared", (Lane.SPEECH_INTERACTIVE, Lane.INTAKE), 1),
        WorkerSpec("media-speech", (Lane.SPEECH_INTERACTIVE,), 1),
    ),
    "default": (
        WorkerSpec("default-ai", (Lane.AI,), 8),
        WorkerSpec("default-background", (Lane.BACKGROUND,), 1),
    ),
}


# Roles whose models the media pool keeps in memory (System Design 5.2, ADR 0028).
MEDIA_ROLES = (Role.TRANSCRIPTION, Role.ALIGNMENT)


async def load_models(pool: str) -> None:
    """Load the speech models of providers marked `preload` in ai.yaml before taking work,
    once per process. The default pool runs no local models."""
    if pool != "media":
        return
    try:
        loaded = await get_gateway().preload(MEDIA_ROLES)
    except ImportError as exc:
        raise SystemExit(
            f"speech libraries missing ({exc}): install the speech extra "
            "(uv sync --extra speech, plus torch and torchaudio) or set "
            "LISTENUP_AI_CONFIG to listenup/ai/ai.fake.yaml"
        ) from exc
    logger.info("models loaded", extra={"pool": pool, "providers": loaded})


async def run_pool(pool: str) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_telemetry(settings, f"worker-{pool}")
    for module in JOB_MODULES:
        __import__(module)

    database = Database(settings.database_url, pool_size=2)
    configure_runtime(database)
    if pool == "media":
        set_gate(Lane.INTAKE, SpeechBacklogGate())
    # Scheduled jobs (the account purge sweep, ADR 0029) tick in the pool of their lane.
    install_schedules(lane for spec in POOLS[pool] for lane in spec.lanes)

    READY_FILE.unlink(missing_ok=True)
    await load_models(pool)
    READY_FILE.write_text(pool)
    logger.info("worker pool ready", extra={"pool": pool})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        async with app.open_async():
            workers = [
                asyncio.create_task(
                    app.run_worker_async(
                        name=spec.name,
                        queues=[lane.value for lane in spec.lanes],
                        concurrency=spec.concurrency,
                        install_signal_handlers=False,
                        shutdown_graceful_timeout=30,
                    )
                )
                for spec in POOLS[pool]
            ]
            if pool == "default":  # one pool samples the queue for the backlog alerts
                workers.append(asyncio.create_task(sample_queue_forever(database)))
            await stop.wait()
            logger.info("worker pool stopping", extra={"pool": pool})
            for task in workers:
                task.cancel()
            for task in workers:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        READY_FILE.unlink(missing_ok=True)
        await database.dispose()
        shutdown_telemetry()


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in POOLS:
        raise SystemExit(f"usage: python -m listenup.worker {{{'|'.join(POOLS)}}}")
    asyncio.run(run_pool(args[0]))


if __name__ == "__main__":
    main()
