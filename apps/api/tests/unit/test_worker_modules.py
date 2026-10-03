"""The worker registers every job the API can queue (ADR 0015)."""

import importlib

from listenup.platform import jobs
from listenup.worker import JOB_MODULES


def test_every_job_module_imports_and_registers_its_jobs() -> None:
    for module in JOB_MODULES:
        importlib.import_module(module)

    assert "identity.send_password_reset" in jobs._registry
