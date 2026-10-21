"""The prompt version written in the prompt file is the one stored in `ai.calls` (#66,
NFR-AI-4, NFR-AI-5), through the real gateway, adapter and PostgreSQL accounting."""

import json
import shutil
from uuid import uuid4

import httpx
import psycopg
import pytest

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import AIConfig, ProviderEntry
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Role
from listenup.ai.prompt_files import PROMPTS_DIR, load_task
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI, version_for
from listenup.ai.registry import Registry
from listenup.ai.tasks import EXAMPLES, GistGrade
from listenup.platform.database import Database
from tests.integration.conftest import conninfo_to_url

INPUT = {
    "key_points": [{"id": "kp1", "text": "It is about sleep.", "kind": "main"}],
    "transcript": "Sleep matters.",
    "gist": "Sleep.",
}


def server(request):
    content = json.dumps(EXAMPLES["grade_gist"])
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 30},
        },
    )


@pytest.mark.anyio
async def test_editing_the_prompt_version_changes_the_version_stored_with_the_call(
    migrated_url, tmp_path
):
    root = tmp_path / "prompts"
    shutil.copytree(PROMPTS_DIR, root)
    provider = "p" + uuid4().hex
    entry = ProviderEntry(
        provider=provider,
        model="qwen3:4b-instruct",
        local=True,
        trains_on_inputs=False,
        accepted=True,
        retries=0,
        options={"base_url": "http://llm:11434/v1", "deployment_version": "digest-1"},
    )
    db = Database(conninfo_to_url(migrated_url))
    try:
        gateway = AIGateway(
            AIConfig(version=1, roles={Role.TEXT_AI: (entry,)}),
            registry=Registry(
                text_ai={
                    provider: lambda e: OpenAICompatibleTextAI(
                        e, transport=httpx.MockTransport(server), prompts_root=root
                    )
                },
                versions={provider: version_for},
            ),
            accounting=PostgresAccounting(db),
        )
        first = await gateway.generate(load_task("grade_gist", root=root), INPUT, GistGrade)
        old = root / "grade_gist" / "v1.md"
        (root / "grade_gist" / "v2.md").write_text(
            old.read_text().replace("version: v1", "version: v2")
        )
        old.unlink()
        second = await gateway.generate(load_task("grade_gist", root=root), INPUT, GistGrade)
        with psycopg.connect(migrated_url) as conn:
            rows = conn.execute(
                "SELECT prompt_version, version, outcome, input_units, output_units "
                "FROM ai.calls WHERE provider=%s ORDER BY created_at",
                [provider],
            ).fetchall()
    finally:
        await db.dispose()
    assert (first.prompt_version, second.prompt_version) == ("v1", "v2")
    stored_version = "openai-chat-v1; structured=json_schema; deployment=digest-1"
    assert rows == [("v1", stored_version, "ok", 90, 30), ("v2", stored_version, "ok", 90, 30)]
