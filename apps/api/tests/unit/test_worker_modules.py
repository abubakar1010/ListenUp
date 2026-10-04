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


def test_the_purge_sweep_is_scheduled_only_in_the_pool_of_its_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0029: the account purge sweep ticks in the default pool (background lane)."""
    from listenup.modules.identity import jobs as identity_jobs

    installed: list[tuple[str, str]] = []

    def periodic(*, cron: str, periodic_id: str) -> Callable[[Any], Any]:
        installed.append((cron, periodic_id))
        return lambda task: task

    # Recorded instead of installed, so no test worker starts queueing sweeps.
    monkeypatch.setattr(jobs.app, "periodic", periodic)
    monkeypatch.setattr(jobs, "_scheduled", set())

    media = [lane for spec in POOLS["media"] for lane in spec.lanes]
    default = [lane for spec in POOLS["default"] for lane in spec.lanes]

    assert jobs.install_schedules(media) == []
    assert jobs.install_schedules(default) == [identity_jobs.PURGE_DUE_ACCOUNTS]
    assert installed == [(identity_jobs.PURGE_SCHEDULE, identity_jobs.PURGE_DUE_ACCOUNTS)]
    # Installing again (a second worker of the pool) registers nothing twice.
    assert jobs.install_schedules(default) == [identity_jobs.PURGE_DUE_ACCOUNTS]
    assert len(installed) == 1
