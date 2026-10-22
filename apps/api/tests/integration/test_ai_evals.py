"""The runner cannot bypass durable gateway admission, even with fake inference."""

from uuid import uuid4

import psycopg
import pytest

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import AIConfig, ProviderEntry
from listenup.ai.evals.runner import run
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Provenance, Role, TextGeneration
from listenup.ai.registry import Registry
from listenup.ai.tasks import EXAMPLES
from listenup.platform.database import Database
from tests.integration.conftest import conninfo_to_url
from tests.unit.ai.test_evals_runner import gist_dataset, thresholds


@pytest.mark.anyio
async def test_evals_respects_persistent_quota_and_logs_each_admitted_attempt(migrated_url):
    provider = "eval" + uuid4().hex
    invoked = []

    class Text:
        async def generate(self, task, input, output_schema):
            invoked.append(task.name)
            return TextGeneration[output_schema](
                provenance=Provenance(provider=provider, model="fixture", version="1"),
                task=task.name,
                prompt_version=task.version,
                value=output_schema.model_validate(EXAMPLES[task.name]),
            )

    entry = ProviderEntry(
        provider=provider,
        model="fixture",
        local=True,
        accepted=True,
        trains_on_inputs=False,
        retries=0,
        limits={"day": {"calls": 2}, "month": {"calls": 2}},
    )
    database = Database(conninfo_to_url(migrated_url))
    try:
        gateway = AIGateway(
            AIConfig(version=1, roles={Role.TEXT_AI: (entry,)}),
            accounting=PostgresAccounting(database),
            registry=Registry(text_ai={provider: lambda _: Text()}),
        )
        report = await run(gist_dataset(), thresholds(), gateway)
    finally:
        await database.dispose()
    assert report["status"] == "fail"
    assert report["successful_attempts"] == 2
    assert report["attempts"] == 3
    assert invoked == ["grade_gist"] * 2
    with psycopg.connect(migrated_url) as connection:
        outcomes = connection.execute(
            "SELECT outcome, count(*) FROM ai.calls WHERE provider = %s GROUP BY outcome",
            [provider],
        ).fetchall()
    assert dict(outcomes) == {"ok": 2, "quota": 1}
