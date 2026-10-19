"""Gateway policy at its provider boundary; no network/model calls."""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from listenup.ai.config import AIConfig, ProviderEntry
from listenup.ai.errors import AIUnavailable
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Provenance, Role, TextGeneration, TextTask, Transcript
from listenup.ai.registry import Registry


class Score(BaseModel):
    score: float = Field(ge=0, le=1)


@pytest.mark.anyio
async def test_response_prose_is_never_logged_as_version(fake_accounting):
    private = "My name is John Smith. I live in Dhaka."
    response = Transcript(
        provenance=Provenance(provider="a", model="m", version=private),
        language="en",
        duration_seconds=1,
        segments=(),
    )
    gateway, _ = make_gateway([{"provider": "a"}], {"a": response})
    await gateway.transcribe(Path("private.wav"))
    assert private not in repr(fake_accounting.calls)
    assert fake_accounting.calls[0]["version"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("bad_version", ["v2", "My name is John Smith."])
async def test_registered_version_mismatch_falls_back(bad_version, fake_accounting):
    response = Transcript(
        provenance=Provenance(provider="a", model="m", version=bad_version),
        language="en",
        duration_seconds=1,
        segments=(),
    )
    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": response})
    gateway._registry.versions.update(a=lambda _: "v1", b=lambda _: "v1")
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["version"] for r in fake_accounting.calls] == [None, "v1"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    ["index", "text", "duplicate", "overlap", "sound_start", "sound_end", "sound_overlap"],
)
async def test_invalid_assessment_falls_back(failure, fake_accounting):
    from listenup.ai.ports import Role, SpeechAssessment

    calls = []
    entries = tuple(
        ProviderEntry(
            provider=p, model="m", local=True, trains_on_inputs=False, accepted=True, retries=0
        )
        for p in ("a", "b")
    )

    class Assessment:
        def __init__(self, entry):
            self.entry = entry

        async def assess(self, *args):
            calls.append(self.entry.provider)
            words = [
                dict(
                    index=0,
                    text="Hello",
                    start=0,
                    end=1,
                    accuracy=0.5,
                    sounds=[dict(label="h", start=0, end=0.5, score=0.5)],
                )
            ]
            if self.entry.provider == "a":
                if failure == "index":
                    words[0]["index"] = 99
                elif failure == "text":
                    words[0]["text"] = "unrelated"
                elif failure == "duplicate":
                    words.append(dict(words[0], start=1, end=2, sounds=[]))
                elif failure == "overlap":
                    words.append(dict(words[0], index=1, text="there", start=0.5, sounds=[]))
                elif failure == "sound_start":
                    words[0]["start"] = 0.25
                elif failure == "sound_end":
                    words[0]["sounds"][0]["end"] = 2
                elif failure == "sound_overlap":
                    words[0]["sounds"].append(dict(label="e", start=0.25, end=0.75, score=0.5))
            return SpeechAssessment(
                provenance=Provenance(provider=self.entry.provider, model="m", version="v1"),
                words=words,
                pauses=(),
                fillers=(),
                pitch=(),
            )

    gateway = AIGateway(
        AIConfig(version=1, roles={Role.SPEECH_ASSESSMENT: entries}),
        registry=Registry(speech_assessment={p: Assessment for p in ("a", "b")}),
    )
    result = await gateway.assess(Path("private.wav"), "Hello there", Path("reference.wav"))
    assert result.provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


class Adapter:
    def __init__(self, entry, events, response=None):
        self.entry, self.events, self.response = entry, events, response

    async def transcribe(self, *args):
        self.events.append(self.entry.provider)
        if isinstance(self.response, Exception):
            raise self.response
        if self.response == "timeout":
            await asyncio.Event().wait()
        if self.response is not None:
            return self.response
        return Transcript(
            provenance=Provenance(provider=self.entry.provider, model="m", version="v1"),
            language="en",
            duration_seconds=1,
            segments=(),
        )

    async def generate(self, task, input, output_schema):
        self.events.append(self.entry.provider)
        return TextGeneration(
            provenance=Provenance(provider=self.entry.provider, model="m", version="v1"),
            task=task.name,
            prompt_version=task.version,
            value=output_schema(score=0.5),
        )


def make_gateway(entries, responses=None, **config):
    events = []
    responses = responses or {}
    factories = {
        e["provider"]: (lambda entry: Adapter(entry, events, responses.get(entry.provider)))
        for e in entries
    }
    providers = tuple(
        ProviderEntry(
            **{
                "model": "m",
                "retries": 0,
                "timeout_seconds": 0.01,
                "local": True,
                "trains_on_inputs": False,
                "accepted": True,
                **e,
            }
        )
        for e in entries
    )
    return AIGateway(
        AIConfig(
            version=1, roles={Role.TRANSCRIPTION: providers, Role.TEXT_AI: providers}, **config
        ),
        registry=Registry(transcription=factories, text_ai=factories),
    ), events


@pytest.mark.anyio
async def test_failure_tries_fallback_in_order():
    gateway, calls = make_gateway(
        [{"provider": "a"}, {"provider": "b"}, {"provider": "c"}],
        {"a": ValueError("private learner text"), "b": ConnectionError("secret")},
    )
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "c"
    assert calls == ["a", "b", "c"]


@pytest.mark.anyio
async def test_timeout_falls_back():
    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": "timeout"})
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["a", "b"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        {"unexpected": "secret"},
        Transcript.model_construct(
            provenance=Provenance(provider="a", model="m", version="v1"),
            language="en",
            duration_seconds=float("inf"),
            segments=(),
        ),
    ],
)
async def test_invalid_output_falls_back(response):
    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": response})
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["a", "b"]


@pytest.mark.anyio
async def test_no_provider_raises_content_free_ai_unavailable():
    gateway, _ = make_gateway(
        [{"provider": "a"}], {"a": ValueError("learner@example.com private text")}
    )
    with pytest.raises(AIUnavailable) as error:
        await gateway.transcribe(Path("private.wav"))
    assert "private" not in str(error.value)
    assert "learner@" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.anyio
async def test_ineligible_provider_never_receives_data():
    gateway, calls = make_gateway(
        [
            {"provider": "a", "trains_on_inputs": True},
            {"provider": "b", "trains_on_inputs": False, "local": True},
        ]
    )
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["b"]


@pytest.mark.anyio
@pytest.mark.parametrize("training", [True, None])
@pytest.mark.parametrize("role", [Role.TRANSCRIPTION, Role.TEXT_AI])
async def test_ineligible_fallback_is_skipped_after_primary_retries(
    training, role, fake_accounting
):
    gateway, calls = make_gateway(
        [
            {"provider": "a", "retries": 1},
            {"provider": "b", "trains_on_inputs": training, "retries": 5},
            {"provider": "c"},
        ],
        {"a": ConnectionError("private learner content")},
    )

    async def no_wait(_):
        pass

    gateway._sleep = no_wait
    if role is Role.TEXT_AI:

        async def fail(task, input, schema):
            calls.append("a")
            raise ConnectionError("private learner gist")

        gateway._registry.text_ai["a"] = lambda _: type(
            "Unavailable", (), {"generate": staticmethod(fail)}
        )()
        result = await gateway.generate(TextTask("grade_gist", "v1"), {"gist": "private"}, Score)
    else:
        result = await gateway.transcribe(Path("private.wav"))
    assert result.provenance.provider == "c"
    assert calls == ["a", "a", "c"]
    assert [row["outcome"] for row in fake_accounting.calls] == [
        "error",
        "error",
        "ineligible",
        "ok",
    ]


@pytest.mark.anyio
async def test_role_and_task_configuration_order():
    gateway, calls = make_gateway(
        [
            {"provider": "a", "trains_on_inputs": False, "local": True},
            {"provider": "b", "trains_on_inputs": False, "local": True},
        ],
        tasks={"grade_gist": ["b", "a"]},
    )
    result = await gateway.generate(TextTask("grade_gist", "v1"), {"gist": "private"}, Score)
    assert result.provenance.provider == "b"
    assert calls == ["b"]


@pytest.mark.anyio
async def test_exhausted_quota_falls_back(fake_accounting):
    fake_accounting.exhausted.add("a")
    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}])
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["quota", "ok"]


@pytest.mark.anyio
async def test_logs_exclude_input_paths_and_error_messages(fake_accounting):
    gateway, _ = make_gateway(
        [{"provider": "a"}, {"provider": "b"}], {"a": ValueError("learner@example.com secret")}
    )
    gateway._registry.versions.update(a=lambda _: "v1", b=lambda _: "v1")
    await gateway.transcribe(Path("users/learner@example.com/private.wav"))
    assert [r["outcome"] for r in fake_accounting.calls] == ["error", "ok"]
    assert "private" not in repr(fake_accounting.calls)
    assert "learner@" not in repr(fake_accounting.calls)
    assert fake_accounting.calls[-1]["version"] == "v1"


@pytest.mark.anyio
async def test_saving_mode_signals_templates_and_preserves_round_three(fake_accounting):
    from listenup.ai.policy import CallContext

    gateway, calls = make_gateway([{"provider": "a"}])
    assert await gateway.quota_saving() is True
    with pytest.raises(AIUnavailable) as error:
        await gateway.generate(
            TextTask("shadow_feedback", "v1"), {}, Score, context=CallContext(round=1)
        )
    assert error.value.reason == "template_feedback"
    assert calls == []
    assert (
        await gateway.generate(
            TextTask("shadow_feedback", "v1"), {}, Score, context=CallContext(round=3)
        )
    ).value.score == 0.5
    assert calls == ["a"]


@pytest.mark.anyio
@pytest.mark.parametrize("remaining,expected", [(0.26, False), (0.25, True), (0.24, True)])
async def test_saving_threshold(fake_accounting, remaining, expected):
    fake_accounting.ratio = remaining
    gateway, _ = make_gateway([{"provider": "a"}], saving_mode=False)
    assert await gateway.quota_saving() is expected


@pytest.mark.anyio
async def test_hosted_eligibility_requires_all_controls():
    from listenup.ai.policy import CallContext

    settings = dict(
        provider="a",
        local=False,
        accepted=True,
        retention_verified=True,
        regions=["approved"],
        populations=["adult"],
    )
    for omitted in ["accepted", "retention_verified", "regions", "populations"]:
        config = {k: v for k, v in settings.items() if k != omitted}
        gateway, calls = make_gateway([config, {"provider": "b"}])
        result = await gateway.transcribe(
            Path("private.wav"),
            context=CallContext(region="approved", population="adult", consent=True),
        )
        assert result.provenance.provider == "b"
        assert calls == ["b"]


@pytest.mark.anyio
async def test_accounting_failure_prevents_unmetered_calls(fake_accounting):
    async def fail(*args):
        raise RuntimeError("secret SQL parameters learner@example.com")

    fake_accounting.admit = fail
    gateway, calls = make_gateway([{"provider": "a"}])
    with pytest.raises(AIUnavailable, match="accounting unavailable"):
        await gateway.transcribe(Path("private.wav"))
    assert calls == []


@pytest.mark.anyio
async def test_cancellation_is_logged_and_never_falls_back(fake_accounting):
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}])
    gateway._factories(Role.TRANSCRIPTION)["a"] = lambda e: type(
        "Blocked", (), {"transcribe": blocked}
    )()
    task = asyncio.create_task(gateway.transcribe(Path("private.wav")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [r["outcome"] for r in fake_accounting.calls] == ["cancelled"]
    assert calls == []


@pytest.mark.anyio
async def test_unknown_hosted_quotas_are_ineligible():
    from listenup.ai.policy import CallContext

    gateway, calls = make_gateway(
        [
            {
                "provider": "a",
                "local": False,
                "accepted": True,
                "retention_verified": True,
                "regions": ["ok"],
                "populations": ["adult"],
            },
            {"provider": "b"},
        ]
    )
    assert (
        await gateway.transcribe(
            Path("private.wav"), context=CallContext(consent=True, region="ok", population="adult")
        )
    ).provenance.provider == "b"
    assert calls == ["b"]


@pytest.mark.anyio
async def test_invalid_token_usage_cannot_release_reserved_capacity(fake_accounting):
    from listenup.ai.ports import Usage

    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}])

    async def oversized(task, input, schema):
        calls.append("a")
        return TextGeneration(
            provenance=Provenance(provider="a", model="m", version="v1"),
            task=task.name,
            prompt_version=task.version,
            value=schema(score=0.5),
            usage=Usage(input_tokens=999999),
        )

    gateway._factories(Role.TEXT_AI)["a"] = lambda e: type(
        "Oversized", (), {"generate": staticmethod(oversized)}
    )()
    assert (
        await gateway.generate(TextTask("grade_gist", "v1"), {}, Score)
    ).provenance.provider == "b"
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


@pytest.mark.anyio
async def test_text_schema_revalidates_constructed_values_and_finite_numbers():
    class Unbounded(BaseModel):
        score: float

    gateway, _ = make_gateway([{"provider": "a"}])

    async def invalid(task, input, schema):
        return TextGeneration(
            provenance=Provenance(provider="a", model="m", version="v1"),
            task=task.name,
            prompt_version=task.version,
            value=schema(score=float("nan")),
        )

    gateway._factories(Role.TEXT_AI)["a"] = lambda e: type(
        "Invalid", (), {"generate": staticmethod(invalid)}
    )()
    with pytest.raises(AIUnavailable):
        await gateway.generate(TextTask("grade_gist", "v1"), {}, Unbounded)


def test_shared_provider_cannot_have_conflicting_limits():
    from listenup.ai.errors import AIConfigError

    entry = ProviderEntry(
        provider="a", model="m", local=True, trains_on_inputs=False, limits={"day": {"calls": 10}}
    )
    config = AIConfig(
        version=1,
        roles={
            Role.TRANSCRIPTION: (entry,),
            Role.TEXT_AI: (entry.model_copy(update={"limits": {"day": {"calls": 20}}}),),
        },
    )
    with pytest.raises(AIConfigError):
        AIGateway(
            config,
            registry=Registry(transcription={"a": lambda e: None}, text_ai={"a": lambda e: None}),
        )


@pytest.mark.anyio
async def test_provenance_cannot_put_email_or_path_in_logs(fake_accounting):
    response = Transcript(
        provenance=Provenance(provider="a", model="m", version="learner@example.com /private/file"),
        language="en",
        duration_seconds=1,
        segments=(),
    )
    gateway, _ = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": response})
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert "learner@" not in repr(fake_accounting.calls)


@pytest.mark.anyio
async def test_fallback_and_queue_delay_are_content_free_metadata(fake_accounting):
    from listenup.ai.policy import CallContext

    gateway, _ = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": ValueError("private")})
    await gateway.transcribe(Path("private.wav"), context=CallContext(queue_delay_seconds=2.5))
    assert [r["fallback_depth"] for r in fake_accounting.calls] == [0, 1]
    assert [r["queue_delay_ms"] for r in fake_accounting.calls] == [2500, 2500]


@pytest.mark.anyio
async def test_unaccepted_local_text_model_is_not_called():
    gateway, calls = make_gateway(
        [{"provider": "a", "accepted": False}, {"provider": "b", "accepted": True}]
    )
    assert (
        await gateway.generate(TextTask("grade_gist", "v1"), {}, Score)
    ).provenance.provider == "b"
    assert calls == ["b"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "control",
    [
        "training",
        "enabled",
        "accepted",
        "retention",
        "region",
        "population",
        "consent",
        "limits",
        None,
    ],
)
async def test_hosted_controls_are_each_enforced(control):
    from listenup.ai.policy import CallContext

    entry = dict(
        provider="a",
        local=False,
        trains_on_inputs=False,
        enabled=True,
        accepted=True,
        retention_verified=True,
        regions=["approved"],
        populations=["adult"],
        limits={"day": {"calls": 100}, "month": {"calls": 1000}, "minute": {"calls": 10}},
    )
    context = dict(region="approved", population="adult", consent=True)
    if control == "training":
        entry["trains_on_inputs"] = True
    elif control == "enabled":
        entry["enabled"] = False
    elif control == "accepted":
        entry["accepted"] = False
    elif control == "retention":
        entry["retention_verified"] = False
    elif control == "region":
        context["region"] = "unknown"
    elif control == "population":
        context["population"] = "unknown"
    elif control == "consent":
        context["consent"] = False
    elif control == "limits":
        entry["limits"] = {}
    gateway, calls = make_gateway([entry, {"provider": "b"}])
    result = await gateway.transcribe(Path("private.wav"), context=CallContext(**context))
    expected = "a" if control is None else "b"
    assert result.provenance.provider == expected
    assert calls == [expected]


@pytest.mark.anyio
async def test_input_and_audio_budget_refusals_do_not_call_provider(fake_accounting):
    gateway, calls = make_gateway(
        [{"provider": "a", "input_token_limit": 10, "prompt_token_budget": 0}]
    )
    with pytest.raises(AIUnavailable):
        await gateway.generate(TextTask("grade_gist", "v1"), {"gist": "x" * 100}, Score)
    assert calls == []
    gateway, calls = make_gateway([{"provider": "a", "limits": {"day": {"audio_seconds": 60}}}])
    with pytest.raises(AIUnavailable):
        await gateway.transcribe(Path("private.wav"))
    assert calls == []


@pytest.mark.anyio
async def test_each_retry_requires_fresh_admission(fake_accounting):
    from listenup.ai.errors import TransientProviderError

    gateway, calls = make_gateway(
        [{"provider": "a", "retries": 2}, {"provider": "b"}],
        {"a": TransientProviderError("private")},
    )

    async def exhaust(_):
        fake_accounting.exhausted.add("a")

    gateway._sleep = exhaust
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["error", "quota", "ok"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "metadata", [TextTask("learner@example.com", "v1"), TextTask("grade_gist", "private/path")]
)
async def test_invalid_task_metadata_is_not_logged(metadata, fake_accounting):
    gateway, calls = make_gateway([{"provider": "a"}])
    with pytest.raises(AIUnavailable, match="invalid task metadata"):
        await gateway.generate(metadata, {}, Score)
    assert calls == []
    assert fake_accounting.calls == []


@pytest.mark.anyio
async def test_all_roles_keep_their_public_methods():
    from listenup.ai.config import FAKE_CONFIG, load_config
    from listenup.ai.providers import fake

    gateway = AIGateway(load_config(FAKE_CONFIG))
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "fake"
    assert (await gateway.align(Path("private.wav"), "hello")).words[0].text == "hello"
    assert (await gateway.assess(Path("private.wav"), "hello", Path("ref.wav"))).words[
        0
    ].text == "hello"
    fake.register_text_response("grade_gist", {"score": 0.5})
    try:
        assert (await gateway.generate(TextTask("grade_gist", "v1"), {}, Score)).value.score == 0.5
    finally:
        fake.clear_text_responses()


@pytest.mark.anyio
async def test_transcript_cannot_exceed_reserved_audio_budget(fake_accounting):
    from listenup.ai.policy import CallContext

    gateway, _ = make_gateway(
        [{"provider": "a", "limits": {"day": {"audio_seconds": 10}}}, {"provider": "b"}]
    )
    result = await gateway.transcribe(Path("private.wav"), context=CallContext(audio_seconds=0.5))
    assert result.provenance.provider == "b"
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


@pytest.mark.anyio
async def test_budget_skips_are_logged_as_quota(fake_accounting):
    gateway, _ = make_gateway([{"provider": "a", "input_token_limit": 1}])
    with pytest.raises(AIUnavailable):
        await gateway.generate(TextTask("grade_gist", "v1"), {"gist": "private"}, Score)
    assert [r["outcome"] for r in fake_accounting.calls] == ["quota"]


@pytest.mark.anyio
async def test_task_specific_token_caps_are_reserved_and_passed_to_adapter(fake_accounting):
    gateway, _ = make_gateway(
        [{"provider": "a"}],
        task_budgets={
            "grade_gist": {"input_tokens": 128, "output_tokens": 32, "prompt_tokens": 16}
        },
    )
    result = await gateway.generate(TextTask("grade_gist", "v1"), {"gist": "hello"}, Score)
    assert result.value.score == 0.5
    reservation = fake_accounting.calls[0]["budget"]
    assert (reservation.input_tokens, reservation.output_tokens) == (128, 32)
    adapter = next(iter(gateway._adapters.values()))
    assert (adapter.entry.input_token_limit, adapter.entry.output_token_limit) == (128, 32)


@pytest.mark.anyio
async def test_cancellation_survives_accounting_failure(fake_accounting):
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    async def fail(*args):
        raise RuntimeError("private database detail")

    fake_accounting.finish = fail
    gateway, _ = make_gateway([{"provider": "a"}])
    gateway._factories(Role.TRANSCRIPTION)["a"] = lambda e: type(
        "Blocked", (), {"transcribe": blocked}
    )()
    task = asyncio.create_task(gateway.transcribe(Path("private.wav")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_mismatched_provider_provenance_falls_back(fake_accounting):
    response = Transcript(
        provenance=Provenance(provider="other", model="m", version="1"),
        language="en",
        duration_seconds=1,
        segments=(),
    )
    gateway, calls = make_gateway([{"provider": "a"}, {"provider": "b"}], {"a": response})
    assert (await gateway.transcribe(Path("private.wav"))).provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["task", "prompt", "size", "range"])
async def test_text_output_contract_refusals_fall_back(failure, fake_accounting):
    gateway, calls = make_gateway([{"provider": "a", "output_token_limit": 8}, {"provider": "b"}])

    class TextAdapter:
        def __init__(self, entry):
            self.entry = entry

        async def generate(self, task, input, output_schema):
            calls.append(self.entry.provider)
            first = self.entry.provider == "a"
            return (
                TextGeneration.model_construct(
                    provenance=Provenance(provider=self.entry.provider, model="m", version="1"),
                    task="other" if first and failure == "task" else task.name,
                    prompt_version="other" if first and failure == "prompt" else task.version,
                    value=Score.model_construct(score=2 if first and failure == "range" else 0.5),
                )
                if failure != "size"
                else {
                    "provenance": {"provider": self.entry.provider, "model": "m", "version": "1"},
                    "task": task.name,
                    "prompt_version": task.version,
                    "value": {"text": "x" * 100 if first else "ok"},
                }
            )

    gateway._registry.text_ai.update(a=TextAdapter, b=TextAdapter)

    class Payload(BaseModel):
        text: str

    schema = Payload if failure == "size" else Score
    assert (
        await gateway.generate(TextTask("grade_gist", "v1"), {}, schema)
    ).provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


@pytest.mark.anyio
async def test_reported_audio_usage_cannot_exceed_reservation(fake_accounting):
    from listenup.ai.policy import CallContext
    from listenup.ai.ports import Usage

    response = Transcript(
        provenance=Provenance(provider="a", model="m", version="1"),
        usage=Usage(audio_seconds=2),
        language="en",
        duration_seconds=0.5,
        segments=(),
    )
    gateway, calls = make_gateway(
        [{"provider": "a", "limits": {"day": {"audio_seconds": 10}}}, {"provider": "b"}],
        {"a": response},
    )
    assert (
        await gateway.transcribe(Path("private.wav"), context=CallContext(audio_seconds=1))
    ).provenance.provider == "b"
    assert calls == ["a", "b"]
    assert [r["outcome"] for r in fake_accounting.calls] == ["invalid_output", "ok"]


@pytest.mark.parametrize(
    "limits",
    [
        {"day": {"calls": -1}},
        {"month": {"tokens": float("inf")}},
        {"minute": {"audio_seconds": float("nan")}},
    ],
)
def test_invalid_quota_configuration_is_rejected(limits):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderEntry(provider="a", limits=limits)


@pytest.mark.parametrize("role", [Role.TRANSCRIPTION, Role.ALIGNMENT, Role.SPEECH_ASSESSMENT])
@pytest.mark.parametrize("period", ["minute", "day", "month"])
@pytest.mark.parametrize("limit", [0, 1])
def test_speech_token_quotas_are_rejected_before_adapter_creation(
    role, period, limit, fake_accounting
):
    from listenup.ai.errors import AIConfigError

    created = []

    def factory(entry):
        created.append(entry.provider)
        raise AssertionError("unsupported quota must fail before adapter creation")

    entry = ProviderEntry(
        provider="a",
        local=True,
        trains_on_inputs=False,
        accepted=True,
        limits={period: {"tokens": limit}},
    )
    with pytest.raises(AIConfigError, match="token quotas require text_ai"):
        AIGateway(
            AIConfig(version=1, roles={role: (entry,)}),
            registry=Registry(
                transcription={"a": factory},
                alignment={"a": factory},
                speech_assessment={"a": factory},
            ),
        )
    assert created == []
    assert fake_accounting.calls == []


def test_duplicate_and_unknown_task_routes_are_rejected():
    from listenup.ai.errors import AIConfigError

    with pytest.raises(AIConfigError, match="duplicate provider"):
        make_gateway([{"provider": "a"}, {"provider": "a"}])
    with pytest.raises(AIConfigError, match="invalid task provider order"):
        make_gateway([{"provider": "a"}], tasks={"grade_gist": ["missing"]})


@pytest.mark.anyio
async def test_valid_usage_is_forwarded_for_actual_settlement(fake_accounting):
    from listenup.ai.ports import Usage

    gateway, _ = make_gateway([{"provider": "a"}])

    async def generate(task, input, schema):
        return TextGeneration(
            provenance=Provenance(provider="a", model="m", version="1"),
            usage=Usage(input_tokens=4, output_tokens=2),
            task=task.name,
            prompt_version=task.version,
            value=schema(score=0.5),
        )

    gateway._registry.text_ai["a"] = lambda e: type(
        "Adapter", (), {"generate": staticmethod(generate)}
    )()
    result = await gateway.generate(TextTask("grade_gist", "v1"), {}, Score)
    assert result.usage == Usage(input_tokens=4, output_tokens=2)
    assert fake_accounting.calls[0]["usage"] == result.usage
    assert fake_accounting.calls[0]["outcome"] == "ok"
