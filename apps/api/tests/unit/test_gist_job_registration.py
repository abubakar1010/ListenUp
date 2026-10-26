"""An API process queues grades without importing the worker or test fixtures."""

import subprocess
import sys


def test_api_submission_registers_grading_job_in_fresh_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
import uuid
from unittest.mock import AsyncMock
from listenup.modules.grading import service
from listenup.platform.jobs import _registry, Lane
service.repository.ensure_pending = AsyncMock()
async def enqueue(db, name, **kwargs):
    assert name in _registry, "API queued an unregistered grading job"
    assert _registry[name].lane is (Lane.AI if name == "grading.grade_gist" else Lane.BACKGROUND)
service.enqueue = enqueue
asyncio.run(service.queue_gist(object(), uuid.uuid4(), uuid.uuid4()))
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
