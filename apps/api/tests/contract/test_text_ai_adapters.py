"""Contract tests for the Text AI adapter (#66, ADR 0045).

Every recording in `recordings/text_ai/` is replayed through the whole adapter over
httpx.MockTransport: the request must have the expected shape and the reply must become the
task's validated Pydantic object. CI makes no network call and holds no API key. The first
recordings are synthetic (documented response shapes): they prove the mapping, not the
models (NFR-AI-6); `scripts/record_ai_contract.py text_ai` replaces them with real ones.
"""

import json
import re
from pathlib import Path

import httpx
import pytest

from listenup.ai.config import load_config
from listenup.ai.ports import Role, TextAIPort, TextGeneration
from listenup.ai.prompt_files import PROMPTS_DIR, load_task
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI, parse_options
from listenup.ai.tasks import TASK_MODELS

RECORDINGS = Path(__file__).parent / "recordings" / "text_ai"
FILES = sorted(RECORDINGS.glob("*.json"))
KEY_PATTERNS = [r"gsk_[A-Za-z0-9]{16,}", r"sk-[A-Za-z0-9]{16,}", r"(?i)authorization", r"Bearer\s"]


def test_both_adapters_have_a_recording_for_every_task():
    pairs = {tuple(f.stem.split("_", 1)) for f in FILES}
    assert pairs == {(p, t) for p in ("groq", "ollama") for t in TASK_MODELS}


@pytest.mark.anyio
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
async def test_recorded_reply_becomes_a_validated_object(path):
    record = json.loads(path.read_text())
    entries = {e.provider: e for e in load_config().providers(Role.TEXT_AI)}
    entry = entries[record["provider"]]
    seen: list[httpx.Request] = []

    def server(request):
        seen.append(request)
        return httpx.Response(record["response"]["status"], json=record["response"]["body"])

    adapter = OpenAICompatibleTextAI(
        entry, transport=httpx.MockTransport(server), environ={"LISTENUP_AI_GROQ_API_KEY": "k"}
    )
    assert isinstance(adapter, TextAIPort)
    model = TASK_MODELS[record["task"]]
    result = await adapter.generate(load_task(record["task"]), record["input"], model)

    assert isinstance(result, TextGeneration) and isinstance(result.value, model)
    assert (result.provenance.provider, result.provenance.model) == (entry.provider, entry.model)
    assert result.prompt_version == load_task(record["task"]).version
    assert result.usage is not None and result.usage.input_tokens > 0
    request = seen[0]
    body = json.loads(request.content)
    assert request.url.path == record["expect"]["path"]
    assert ("authorization" in request.headers) is record["expect"]["sends_key"]
    assert body["temperature"] == 0 and body["max_tokens"] == entry.output_token_limit
    assert body["response_format"]["json_schema"]["name"] == record["task"]
    assert parse_options(entry).structured_output == "json_schema"


def test_repository_files_hold_no_api_keys():
    """Keys come from the environment only (NFR-AI-3 deployment rule)."""
    files = [
        *FILES,
        *PROMPTS_DIR.rglob("*"),
        Path(load_config.__globals__["DEFAULT_CONFIG"]),
        Path(load_config.__globals__["FAKE_CONFIG"]),
    ]
    for file in files:
        if file.is_file():
            text = file.read_text()
            for pattern in KEY_PATTERNS:
                assert not re.search(pattern, text), f"{file.name} matches {pattern}"
