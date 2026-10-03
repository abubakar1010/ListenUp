"""Worker entry point: `procrastinate --app=listenup.worker.app worker --queues=<lanes>`.

Queue lanes (System Design section 4): the media pool serves `speech-interactive`
and `intake`; the default pool serves `ai` and `background`.
"""

import procrastinate

from listenup.platform.config import get_settings

LANES = ("speech-interactive", "intake", "ai", "background")

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().database_url),
)
