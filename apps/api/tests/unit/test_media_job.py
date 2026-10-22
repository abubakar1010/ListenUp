import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from listenup.platform import media_job
from listenup.platform.jobs import PermanentError
from listenup.platform.log import current_request_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,status",
    [
        (None, None),
        (PermanentError("unsafe"), 65),
        (MemoryError(), 70),
        (ConnectionError("private storage URL must not be printed"), 75),
    ],
)
async def test_child_dispatch_disposes_database_and_classifies_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, status: int | None
) -> None:
    async def handler(deps, **args):
        assert deps.job_id == 17 and deps.attempt == 2
        assert args == {"content_id": "a"}
        assert current_request_id() == "request-17"
        if error:
            raise error

    database = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(media_job, "Database", Mock(return_value=database))
    monkeypatch.setattr(media_job, "JOB_MODULES", ["json"])
    monkeypatch.setattr(media_job, "_registry", {"test.child": SimpleNamespace(handler=handler)})
    monkeypatch.setattr(media_job, "configure_logging", Mock())
    monkeypatch.setattr(
        media_job.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "name": "test.child",
                    "job_id": 17,
                    "attempt": 2,
                    "args": {"content_id": "a"},
                    "request_id": "request-17",
                }
            )
        ),
    )
    if status is None:
        await media_job.main()
    else:
        with pytest.raises(SystemExit) as raised:
            await media_job.main()
        assert raised.value.code == status
    database.dispose.assert_awaited_once()
