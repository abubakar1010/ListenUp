"""The worker registers every job the API can queue (ADR 0015)."""

import importlib
from collections.abc import Callable
from typing import Any

import pytest

from listenup.platform import jobs
from listenup.worker import JOB_MODULES, POOLS


def test_every_job_module_imports_and_registers_its_jobs() -> None:
    for module in JOB_MODULES:
        importlib.import_module(module)

    assert "identity.send_password_reset" in jobs._registry
    assert jobs._registry["cards.generate_snippet"].lane is jobs.Lane.INTAKE
    assert jobs._registry["cards.cleanup_snippets"].lane is jobs.Lane.BACKGROUND
    assert jobs._registry["library.delete_content"].lane is jobs.Lane.BACKGROUND


def test_scheduled_jobs_run_only_in_the_pool_of_their_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0029: the account purge sweep and the stalled-job recovery tick in the
    default pool (background lane)."""
    from listenup.modules.cards import jobs as card_jobs
    from listenup.modules.identity import jobs as identity_jobs

    importlib.import_module("listenup.ai.jobs")
    importlib.import_module("listenup.modules.library.jobs")

    installed: list[tuple[str, str]] = []

    def periodic(*, cron: str, periodic_id: str) -> Callable[[Any], Any]:
        installed.append((cron, periodic_id))
        return lambda task: task

    # Recorded instead of installed, so no test worker starts queueing sweeps.
    monkeypatch.setattr(jobs.app, "periodic", periodic)
    monkeypatch.setattr(jobs, "_scheduled", set())

    media = [lane for spec in POOLS["media"] for lane in spec.lanes]
    default = [lane for spec in POOLS["default"] for lane in spec.lanes]
    scheduled = [
        jobs.RECOVER_STALLED_JOBS,
        identity_jobs.PURGE_DUE_ACCOUNTS,
        "ai.maintain",
        card_jobs.CLEANUP,
        "library.reconcile_content_deletions",
    ]

    assert jobs.install_schedules(media) == []
    assert set(jobs.install_schedules(default)) == set(scheduled)
    assert set(installed) == {
        (jobs.RECOVER_SCHEDULE, jobs.RECOVER_STALLED_JOBS),
        (identity_jobs.PURGE_SCHEDULE, identity_jobs.PURGE_DUE_ACCOUNTS),
        ("*/5 * * * *", "ai.maintain"),
        ("* * * * *", card_jobs.CLEANUP),
        ("* * * * *", "library.reconcile_content_deletions"),
    }
    # Installing again (a second worker of the pool) registers nothing twice.
    assert set(jobs.install_schedules(default)) == set(scheduled)
    assert len(installed) == 5


@pytest.mark.anyio
@pytest.mark.parametrize("pool", ["media", "default"])
async def test_pool_enables_process_isolation_before_accepting_jobs(
    pool: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from listenup import worker

    database = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(jobs._runtime, "database", None)
    monkeypatch.setattr(jobs._runtime, "isolate_media", False)
    monkeypatch.setattr(worker, "Database", Mock(return_value=database))
    monkeypatch.setattr(worker, "JOB_MODULES", ["json"])
    monkeypatch.setattr(worker, "load_models", AsyncMock())
    monkeypatch.setattr(worker, "configure_logging", Mock())
    monkeypatch.setattr(worker, "configure_telemetry", Mock())
    monkeypatch.setattr(worker, "shutdown_telemetry", Mock())
    monkeypatch.setattr(worker, "install_schedules", Mock())
    monkeypatch.setattr(worker, "set_gate", Mock())
    monkeypatch.setattr(worker, "sample_queue_forever", AsyncMock())
    monkeypatch.setattr(worker, "READY_FILE", tmp_path / "ready")
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", Mock())

    class StopAtReadiness:
        async def wait(self):
            assert worker.READY_FILE.read_text() == pool
            assert jobs._runtime.database is database
            assert jobs._runtime.isolate_media is (pool == "media")

        def set(self):
            pass

    @asynccontextmanager
    async def opened():
        yield

    monkeypatch.setattr(worker.asyncio, "Event", StopAtReadiness)
    monkeypatch.setattr(worker.app, "open_async", opened)
    monkeypatch.setattr(worker.app, "run_worker_async", AsyncMock())
    await worker.run_pool(pool)
    assert not worker.READY_FILE.exists()
    database.dispose.assert_awaited_once()
