"""Text AI through the gateway with the real adapter over a mock server (#66)."""

import json
import shutil
from dataclasses import replace

import httpx
import pytest

from listenup.ai.config import AIConfig, ProviderEntry, load_config
from listenup.ai.errors import AIUnavailable
from listenup.ai.gateway import AIGateway
from listenup.ai.policy import CallContext
from listenup.ai.ports import Role
from listenup.ai.prompt_files import PROMPTS_DIR, load_prompt, load_task
from listenup.ai.prompt_render import fit, serialized_size
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI, version_for
from listenup.ai.registry import DEFAULT_REGISTRY, Registry
from listenup.ai.tasks import EXAMPLES, GistGrade

HOSTED = "https://hosted.example/v1"
LOCAL = "http://llm:11434/v1"
GRADE_INPUT = {
    "key_points": [{"id": "kp1", "text": "It is about sleep.", "kind": "main"}],
    "transcript": "Sleep matters. Adults need eight hours.",
    "gist": "I heard about sleep.",
}
CONSENT = CallContext(consent=True, region="eu", population="adult")


def reply(content):
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }


class Servers:
    """Mock servers by host; records every request, so 'nothing was sent' is checkable."""

    def __init__(self, **answers):
        self.requests: list[httpx.Request] = []
        self.answers = {
            "hosted.example": json.dumps(EXAMPLES["grade_gist"]),
            "llm": json.dumps(EXAMPLES["grade_gist"]),
        }
        self.answers.update(answers)

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(200, json=reply(self.answers[request.url.host]))

    def hosts(self):
        return [r.url.host for r in self.requests]


def hosted(**change):
    base = dict(
        provider="groq",
        model="hosted-20b",
        trains_on_inputs=False,
        accepted=True,
        retention_verified=True,
        regions=("eu",),
        populations=("adult",),
        limits={"day": {"calls": 100}, "month": {"calls": 1000}},
        retries=0,
        options={"base_url": HOSTED, "api_key_env": "LISTENUP_AI_TEST_API_KEY"},
    )
    return ProviderEntry(**{**base, **change})


def local(**change):
    base = dict(
        provider="ollama",
        model="qwen3:4b-instruct",
        local=True,
        trains_on_inputs=False,
        accepted=True,
        retries=0,
        options={"base_url": LOCAL},
    )
    return ProviderEntry(**{**base, **change})


def build(servers, entries, *, tasks=None, environ=None, prompts_root=PROMPTS_DIR, **config):
    environ = {"LISTENUP_AI_TEST_API_KEY": "k"} if environ is None else environ

    def factory(entry):
        return OpenAICompatibleTextAI(
            entry,
            transport=httpx.MockTransport(servers),
            environ=environ,
            prompts_root=prompts_root,
        )

    ids = {e.provider for e in entries}
    registry = Registry(text_ai={i: factory for i in ids}, versions={i: version_for for i in ids})
    return AIGateway(
        AIConfig(version=1, roles={Role.TEXT_AI: tuple(entries)}, tasks=tasks or {}, **config),
        registry=registry,
    )


async def grade(gateway, input=GRADE_INPUT, context=CONSENT):
    return await gateway.generate(load_task("grade_gist"), input, GistGrade, context=context)


@pytest.mark.anyio
async def test_switching_provider_is_a_configuration_change_only(fake_accounting):
    servers = Servers()
    hosted_first = build(servers, [hosted(), local()])
    local_first = build(servers, [local(), hosted()])
    assert (await grade(hosted_first)).provenance.provider == "groq"
    assert (await grade(local_first)).provenance.provider == "ollama"
    assert servers.hosts() == ["hosted.example", "llm"]


@pytest.mark.anyio
async def test_invalid_output_from_the_first_provider_falls_back_to_the_second(fake_accounting):
    servers = Servers(**{"hosted.example": "not json"})
    result = await grade(build(servers, [hosted(), local()]))
    assert result.provenance.provider == "ollama"
    assert servers.hosts() == ["hosted.example", "llm"]
    assert [c["outcome"] for c in fake_accounting.calls] == [
        "error",
        "ok",
    ]  # adapter-side validation failures log as error (ADR 0046)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        {"trains_on_inputs": None},  # unknown training policy is denied (ADR 0041)
        {"trains_on_inputs": True},
        {"enabled": False},
        {"accepted": False},
        {"retention_verified": False},
        {"regions": ("us",)},
        {"populations": ("minor",)},
        {"limits": {}},
    ],
)
async def test_ineligible_hosted_provider_receives_no_request(change, fake_accounting):
    servers = Servers()
    result = await grade(build(servers, [hosted(**change), local()]))
    assert result.provenance.provider == "ollama"
    assert servers.hosts() == ["llm"]


@pytest.mark.anyio
async def test_hosted_provider_receives_nothing_without_consent(fake_accounting):
    servers = Servers()
    await grade(build(servers, [hosted(), local()]), context=CallContext())
    assert servers.hosts() == ["llm"]


@pytest.mark.anyio
async def test_missing_api_key_sends_nothing_to_the_hosted_server(fake_accounting):
    servers = Servers()
    result = await grade(build(servers, [hosted(), local()], environ={}))
    assert result.provenance.provider == "ollama"
    assert servers.hosts() == ["llm"]


@pytest.mark.anyio
async def test_nothing_is_sent_when_no_provider_is_eligible(fake_accounting):
    servers = Servers()
    with pytest.raises(AIUnavailable):
        await grade(build(servers, [hosted(trains_on_inputs=None), local(accepted=False)]))
    assert servers.requests == []


@pytest.mark.anyio
async def test_unaccepted_local_model_is_not_used(fake_accounting):
    servers = Servers()
    with pytest.raises(AIUnavailable):
        await grade(build(servers, [local(accepted=False)]))
    assert servers.requests == []


@pytest.mark.anyio
async def test_hosted_exhausted_quota_falls_back_to_the_local_server(fake_accounting):
    fake_accounting.exhausted.add("groq")
    servers = Servers()
    result = await grade(build(servers, [hosted(), local()]))
    assert result.provenance.provider == "ollama"
    assert servers.hosts() == ["llm"]


def copy_prompts(tmp_path):
    root = tmp_path / "prompts"
    shutil.copytree(PROMPTS_DIR, root)
    return root


def bump(root, new):
    folder = root / "grade_gist"
    old = load_prompt("grade_gist", root=root).version
    text = (folder / f"{old}.md").read_text().replace(f"version: {old}", f"version: {new}")
    (folder / f"{old}.md").unlink()
    (folder / f"{new}.md").write_text(text)


@pytest.mark.anyio
async def test_changing_the_prompt_version_in_the_file_changes_the_recorded_version(
    tmp_path, fake_accounting
):
    root = copy_prompts(tmp_path)
    gateway = build(Servers(), [local()], prompts_root=root)
    first = await gateway.generate(load_task("grade_gist", root=root), GRADE_INPUT, GistGrade)
    bump(root, "v2")
    second = await gateway.generate(load_task("grade_gist", root=root), GRADE_INPUT, GistGrade)
    assert (first.prompt_version, second.prompt_version) == ("v1", "v2")
    assert [c["prompt"] for c in fake_accounting.calls] == ["v1", "v2"]


def test_shipped_text_entries_are_disabled_until_accepted():
    entries = load_config().providers(Role.TEXT_AI)
    assert [e.provider for e in entries] == ["groq", "ollama"]
    for entry in entries:
        assert not entry.enabled and not entry.accepted
    assert not entries[0].local and entries[0].trains_on_inputs is False
    assert not entries[0].retention_verified and entries[1].local


def test_shipped_configuration_builds_a_gateway_with_valid_options_and_task_order():
    config = load_config()
    gateway = AIGateway(config, registry=DEFAULT_REGISTRY)
    assert config.tasks["extract_key_points"] == ("groq", "ollama")
    assert config.tasks["grade_gist"] == ("groq", "ollama")
    assert config.tasks["shadow_feedback"] == ("ollama", "groq")
    for entry in config.providers(Role.TEXT_AI):
        assert DEFAULT_REGISTRY.versions[entry.provider](entry).startswith("openai-chat-v1")
        assert gateway.text_input_budget("grade_gist") > 0
    assert set(config.task_budgets) == {"extract_key_points", "grade_gist", "shadow_feedback"}


@pytest.mark.anyio
async def test_shipped_configuration_sends_nothing_because_nothing_is_enabled(fake_accounting):
    gateway = AIGateway(load_config(), registry=DEFAULT_REGISTRY)
    with pytest.raises(AIUnavailable):
        await grade(gateway)
    assert all(c["outcome"] == "ineligible" for c in fake_accounting.calls)


@pytest.mark.anyio
async def test_over_budget_reference_text_is_trimmed_before_it_is_sent(fake_accounting):
    entry = local(input_token_limit=900, prompt_token_budget=300)
    servers = Servers()
    gateway = build(servers, [entry])
    long_input = {**GRADE_INPUT, "transcript": "Sleep matters a lot. " * 200}
    with pytest.raises(AIUnavailable):  # the gateway refuses oversized input as it always did
        await grade(gateway, long_input)
    assert servers.requests == []

    budget = gateway.text_input_budget("grade_gist")
    assert budget == 600
    fitted = fit(load_prompt("grade_gist"), long_input, budget)
    result = await grade(gateway, fitted.input)
    assert result.provenance.provider == "ollama"
    sent = json.loads(servers.requests[0].content)["messages"][1]["content"]
    data = json.loads(sent.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert serialized_size(data) <= budget
    assert data["transcript"].endswith("[truncated]")
    assert data["gist"] == GRADE_INPUT["gist"]


@pytest.mark.anyio
async def test_text_input_budget_matches_the_gateways_own_refusal_boundary(fake_accounting):
    config = AIConfig(
        version=1,
        roles={Role.TEXT_AI: (local(input_token_limit=500, prompt_token_budget=100),)},
        task_budgets={
            "grade_gist": {"input_tokens": 400, "output_tokens": 50, "prompt_tokens": 150}
        },
    )
    gateway = AIGateway(config, registry=replace(Registry(), text_ai={"ollama": lambda e: None}))
    assert gateway.text_input_budget("grade_gist") == 250
    assert gateway.text_input_budget("extract_key_points") == 400  # the entry's own limits


def test_text_input_budget_is_the_smallest_across_the_tasks_providers(fake_accounting):
    entries = (
        hosted(input_token_limit=3000, prompt_token_budget=500),
        local(input_token_limit=1200, prompt_token_budget=400),
    )
    gateway = build(Servers(), entries)
    assert gateway.text_input_budget("grade_gist") == 800
    only_hosted = build(Servers(), entries, tasks={"grade_gist": ("groq",)})
    assert only_hosted.text_input_budget("grade_gist") == 2500


@pytest.mark.anyio
async def test_input_of_exactly_the_budget_is_sent_and_one_byte_more_is_refused(
    fake_accounting,
):
    servers = Servers()
    gateway = build(servers, [local(input_token_limit=900, prompt_token_budget=300)])
    budget = gateway.text_input_budget("grade_gist")

    def sized(size):
        data = {**GRADE_INPUT, "transcript": ""}
        return {**data, "transcript": "x" * (size - serialized_size(data))}

    with pytest.raises(AIUnavailable):
        await grade(gateway, sized(budget + 1))
    assert servers.requests == []
    await grade(gateway, sized(budget))
    assert len(servers.requests) == 1


def test_text_input_budget_with_no_provider_is_unavailable(fake_accounting):
    gateway = AIGateway(AIConfig(version=1, roles={}), registry=Registry())
    with pytest.raises(AIUnavailable):
        gateway.text_input_budget("grade_gist")
