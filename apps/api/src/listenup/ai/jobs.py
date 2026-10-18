"""Gateway operations: refresh quota gauges and maintain monthly partitions."""

from pathlib import Path

from sqlalchemy import text

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import load_config
from listenup.ai.ports import Role
from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, job


@job(Lane.BACKGROUND, "ai.maintain", schedule="*/5 * * * *")
async def maintain(deps: JobDeps, timestamp: int | None = None) -> None:
    async with deps.database.transaction() as session:
        await session.execute(text("SELECT ai.maintain_partitions()"))
    settings = get_settings()
    config = load_config(Path(settings.ai_config) if settings.ai_config else None)
    store = PostgresAccounting(deps.database)
    seen = set()
    for role in Role:
        for entry in config.providers(role):
            if entry.provider not in seen:
                await store.remaining(entry)
                seen.add(entry.provider)
