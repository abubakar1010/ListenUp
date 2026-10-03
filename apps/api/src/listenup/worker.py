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

from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.jobs import Lane, SpeechBacklogGate, app, configure_runtime, set_gate
from listenup.platform.log import configure_logging

logger = logging.getLogger(__name__)

READY_FILE = Path("/tmp/listenup-worker-ready")

# Modules whose job handlers this process registers. Each feature story adds its
# module's jobs package here.
JOB_MODULES: list[str] = ["listenup.modules.identity.jobs"]


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


async def load_models(pool: str) -> None:
    """Load speech models before taking work. The speech stories (#18 to #21) fill this in."""


async def run_pool(pool: str) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    for module in JOB_MODULES:
        __import__(module)

    database = Database(settings.database_url, pool_size=2)
    configure_runtime(database)
    if pool == "media":
        set_gate(Lane.INTAKE, SpeechBacklogGate())

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


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in POOLS:
        raise SystemExit(f"usage: python -m listenup.worker {{{'|'.join(POOLS)}}}")
    asyncio.run(run_pool(args[0]))


if __name__ == "__main__":
    main()
