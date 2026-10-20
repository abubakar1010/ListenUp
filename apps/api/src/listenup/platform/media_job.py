"""Private child entry point; the supervisor retains queue ownership (ADR 0049)."""

import asyncio
import json
import sys

from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError, _registry
from listenup.platform.log import configure_logging, request_id_bound
from listenup.worker import JOB_MODULES


async def main() -> None:
    payload = json.load(sys.stdin)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    for module in JOB_MODULES:
        __import__(module)
    database = Database(get_settings().database_url, pool_size=1)
    try:
        entry = _registry[payload["name"]]
        with request_id_bound(payload.get("request_id")):
            await entry.handler(
                JobDeps(database, payload["job_id"], payload["attempt"]), **payload["args"]
            )
    except PermanentError:
        raise SystemExit(65) from None
    except MemoryError:
        raise SystemExit(70) from None
    except Exception:
        # Never leak provider text, storage URLs or connection strings via a
        # subprocess traceback. The supervisor records a fixed failure category.
        raise SystemExit(75) from None
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
