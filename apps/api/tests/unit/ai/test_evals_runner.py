import asyncio
import json
from pathlib import Path

import pytest

from listenup.ai.config import AIConfig, ProviderEntry
from listenup.ai.evals.models import Dataset, Thresholds
from listenup.ai.evals.runner import run
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Provenance, Role, TextGeneration
from listenup.ai.registry import Registry
from listenup.ai.tasks import EXAMPLES

ROOT = Path(__file__).resolve().parents[5]


def gist_dataset():
    return Dataset.model_validate(
        {
            "version": 1,
            "id": "test-gists",
            "kind": "synthetic",
            "suite": "gist",
            "source": "Invented test data, not teacher grades",
            "cases": [
                {
                    "id": "sleep",
                    "smoke": True,
                    "input": {
                        "transcript": "Sleep matters. Adults need eight hours. Screens hurt sleep.",
                        "gist": "Sleep matters.",
                        "key_points": [{"id": "kp1", "text": "Sleep matters", "kind": "main"}],
                    },
                    "expected": {
                        "scores": {"main_idea": 80, "key_details": 60, "accuracy": 100},
                        "overall": 78,
                        "level": "Good",
                    },
                }
            ],
        }
    )


def thresholds(suite="gist"):
    names = ("main_idea", "key_details", "accuracy", "overall")
    rules = {f"{metric}.{name}": {"max": 0} for metric in ("mae", "max_range") for name in names}
    rules["level_agreement"] = {"min": 1}
    return Thresholds.model_validate(
        {
            "version": 1,
            "scope": "synthetic",
            "rules": {suite: rules},
            "gist_level_bounds": [40, 60, 90],
        }
    )


def make_gateway(fake_accounting, providers=("a",), *, wrong=()):
    calls = []

    class Text:
        def __init__(self, entry):
            self.entry = entry

        async def generate(self, task, input, output_schema):
            calls.append(self.entry.provider)
            payload = dict(EXAMPLES["grade_gist"])
            if self.entry.provider in wrong:
                payload["dimension_scores"] = {"main_idea": 0, "key_details": 0, "accuracy": 0}
            return TextGeneration[output_schema](
                provenance=Provenance(
                    provider=self.entry.provider, model=self.entry.model, version="test-v1"
                ),
                task=task.name,
                prompt_version=task.version,
                value=output_schema.model_validate(payload),
            )

    config = AIConfig(
        version=1,
        roles={
            Role.TEXT_AI: tuple(
                ProviderEntry(
                    provider=p,
                    model="m",
                    accepted=True,
                    local=True,
                    trains_on_inputs=False,
                    retries=0,
                )
                for p in providers
            )
        },
    )
    return AIGateway(
        config,
        registry=Registry(text_ai=dict.fromkeys(providers, Text)),
        accounting=fake_accounting,
    ), calls


def test_config_provider_switch_changes_report_and_verdict(fake_accounting):
    a, _ = make_gateway(fake_accounting)
    b, _ = make_gateway(fake_accounting, ("b",), wrong=("b",))
    first = asyncio.run(run(gist_dataset(), thresholds(), a))
    second = asyncio.run(run(gist_dataset(), thresholds(), b))
    assert first["status"] == "pass"
    assert second["status"] == "fail"
    assert first["cases"][0]["runs"][0]["provenance"]["provider"] == "a"
    assert second["cases"][0]["runs"][0]["provenance"]["provider"] == "b"
    assert first["model_quality_evidence"] is False


def test_gateway_quota_denial_is_reported_and_not_dropped(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    fake_accounting.exhausted.add("a")
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway))
    assert report["status"] == "fail"
    assert report["attempts"] == 3
    assert report["successful_attempts"] == 0
    assert report["metrics"] == {}
    assert len(report["cases"][0]["runs"]) == 3
    assert calls == []


def test_gateway_eligibility_denial_and_fallback_are_visible(fake_accounting):
    gateway, calls = make_gateway(fake_accounting, ("a", "b"))
    fake_accounting.exhausted.add("a")
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway))
    assert report["status"] == "pass"
    assert report["requested_provider"] == "a"
    assert report["actual_providers"] == ["b"]
    assert report["provider_acceptance"] is False
    assert calls == ["b"] * 3


@pytest.mark.parametrize("smoke,accepted", [(False, True), (True, False)])
def test_teacher_primary_acceptance_excludes_smoke(fake_accounting, smoke, accepted):
    # Teacher scope exercises report branches only; these are deterministic test doubles,
    # not teacher assets or evidence of any real provider's quality or acceptance.
    dataset = gist_dataset().model_copy(update={"kind": "teacher"})
    config = thresholds().model_copy(update={"scope": "teacher"})
    gateway, calls = make_gateway(fake_accounting)
    report = asyncio.run(run(dataset, config, gateway, smoke=smoke))
    assert report["status"] == "pass"
    assert report["attempts"] == report["successful_attempts"] == 3
    assert report["requested_provider"] == "a"
    assert report["actual_providers"] == ["a"]
    assert report["model_quality_evidence"] is True
    assert report["provider_acceptance"] is accepted
    assert calls == ["a"] * 3


@pytest.mark.parametrize("primary_successes", [0, 1])
def test_teacher_fallback_success_never_accepts_requested_provider(
    fake_accounting, monkeypatch, primary_successes
):
    dataset = gist_dataset().model_copy(update={"kind": "teacher"})
    config = thresholds().model_copy(update={"scope": "teacher"})
    gateway, calls = make_gateway(fake_accounting, ("a", "b"))
    if primary_successes:
        finish = fake_accounting.finish

        async def exhaust_after_primary_success(ticket, *args):
            await finish(ticket, *args)
            if ticket.provider == "a":
                fake_accounting.exhausted.add("a")

        monkeypatch.setattr(fake_accounting, "finish", exhaust_after_primary_success)
    else:
        fake_accounting.exhausted.add("a")
    report = asyncio.run(run(dataset, config, gateway))
    assert report["status"] == "pass"
    assert report["attempts"] == report["successful_attempts"] == 3
    assert report["model_quality_evidence"] is True
    assert report["requested_provider"] == "a"
    assert report["actual_providers"] == (["a", "b"] if primary_successes else ["b"])
    assert report["provider_acceptance"] is False
    assert calls == ["a"] * primary_successes + ["b"] * (3 - primary_successes)


@pytest.mark.parametrize("fallback", [False, True])
def test_teacher_task_override_acceptance_uses_effective_provider(fake_accounting, fallback):
    dataset = gist_dataset().model_copy(update={"kind": "teacher"})
    config = thresholds().model_copy(update={"scope": "teacher"})
    gateway, calls = make_gateway(fake_accounting, ("a", "b"))
    gateway._config.tasks["grade_gist"] = ("b", "a")
    if fallback:
        fake_accounting.exhausted.add("b")
    report = asyncio.run(run(dataset, config, gateway, task_provider="b"))
    actual = "a" if fallback else "b"
    assert report["status"] == "pass"
    assert report["attempts"] == report["successful_attempts"] == 3
    assert report["model_quality_evidence"] is True
    assert report["role_provider"] == "a"
    assert report["requested_provider"] == "b"
    assert report["actual_providers"] == [actual]
    assert report["provider_acceptance"] is (not fallback)
    assert calls == [actual] * 3


@pytest.mark.parametrize("maximum_error,status", [(1, "pass"), (2, "fail")])
def test_shadow_filler_gate_checks_worst_error_at_inclusive_bound(
    fake_accounting, maximum_error, status
):
    data = json.loads((ROOT / "ai-evals/fixtures/shadow.json").read_text())
    case = data["cases"][0]
    case["synthetic_runs"][2]["filler_count"] = case["expected"]["filler_count"] + maximum_error
    config_data = json.loads((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    # Keep every other grade exact, so only the worst-count gate determines the verdict.
    del config_data["rules"]["shadow"]["filler_count_mae"]
    config_data["rules"]["shadow"]["filler_count_max_error"] = {"max": 1}
    gateway, calls = make_gateway(fake_accounting)
    report = asyncio.run(
        run(
            Dataset.model_validate(data),
            Thresholds.model_validate(config_data),
            gateway,
            offline=True,
        )
    )
    assert report["status"] == status
    assert report["attempts"] == report["successful_attempts"] == 6
    assert report["metrics"]["filler_count_mae"] == pytest.approx(maximum_error / 6)
    assert report["metrics"]["filler_count_max_error"] == maximum_error
    assert report["thresholds"]["filler_count_max_error"] == {
        "max": 1,
        "actual": maximum_error,
        "pass": status == "pass",
    }
    assert report["execution"] == "synthetic_report_contract"
    assert report["model_quality_evidence"] is False
    assert report["provider_acceptance"] is False
    assert calls == []


def test_missing_thresholds_or_smoke_cases_cannot_pass(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    empty = thresholds().model_copy(update={"rules": {"gist": {}}})
    report = asyncio.run(run(gist_dataset(), empty, gateway))
    assert report["status"] == "unconfigured"
    assert calls == []
    dataset = gist_dataset().model_copy(
        update={"cases": (gist_dataset().cases[0].model_copy(update={"smoke": False}),)}
    )
    report = asyncio.run(run(dataset, thresholds(), gateway, smoke=True))
    assert report["status"] == "fail"
    assert report["reason"] == "empty_selection"


def test_report_does_not_include_input_or_feedback(fake_accounting):
    gateway, _ = make_gateway(fake_accounting)
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway))
    serialized = json.dumps(report)
    assert "Sleep matters" not in serialized
    assert "You caught" not in serialized
    assert report["cases"][0]["runs"][0]["prompt_version"] == "v1"


def test_live_shadow_is_explicitly_unavailable(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    dataset = Dataset.model_validate_json((ROOT / "ai-evals/fixtures/shadow.json").read_text())
    config = Thresholds.model_validate_json((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    report = asyncio.run(run(dataset, config, gateway))
    assert report["status"] == "unavailable"
    assert report["reason"] == "shadow_scoring_service_unavailable"
    assert report["attempts"] == 0
    assert calls == []


def test_synthetic_shadow_exercises_report_contract_only(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    dataset = Dataset.model_validate_json((ROOT / "ai-evals/fixtures/shadow.json").read_text())
    config = Thresholds.model_validate_json((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    report = asyncio.run(run(dataset, config, gateway, offline=True, smoke=True))
    assert report["status"] == "pass"
    assert report["execution"] == "synthetic_report_contract"
    assert report["model_quality_evidence"] is False
    assert report["provider_acceptance"] is False
    assert report["selected_cases"] == 1
    assert report["actual_providers"] == []
    assert calls == []


def test_ineligible_provider_never_sees_fixture_input(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    gateway._config.roles[Role.TEXT_AI] = (
        gateway.entry(Role.TEXT_AI).model_copy(update={"trains_on_inputs": True}),
    )
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway))
    assert report["status"] == "fail"
    assert calls == []
    assert all(row["outcome"] == "ineligible" for row in fake_accounting.calls)


def test_incomplete_metric_configuration_cannot_pass(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    config = thresholds()
    del config.rules["gist"]["mae.accuracy"]
    report = asyncio.run(run(gist_dataset(), config, gateway))
    assert report["status"] == "unconfigured"
    assert calls == []


def test_offline_teacher_data_cannot_be_scored(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    data = gist_dataset().model_copy(update={"kind": "teacher"})
    report = asyncio.run(run(data, thresholds(), gateway, offline=True))
    assert report["status"] == "unavailable"
    assert report["reason"] == "offline_requires_synthetic_dataset"
    assert calls == []


@pytest.mark.parametrize(
    "scores,overall",
    [
        ({"main_idea": 100, "key_details": 0, "accuracy": 0}, 50),
        ({"main_idea": 0, "key_details": 100, "accuracy": 0}, 30),
        ({"main_idea": 0, "key_details": 0, "accuracy": 100}, 20),
    ],
)
def test_gist_weights_follow_existing_rubric(scores, overall):
    from listenup.ai.evals.runner import gist_grade
    from listenup.ai.tasks import GistGrade

    payload = {**EXAMPLES["grade_gist"], "dimension_scores": scores}
    assert gist_grade(GistGrade.model_validate(payload), (40, 60, 90)).overall == overall


def test_unknown_covered_point_is_not_accepted(fake_accounting, monkeypatch):
    monkeypatch.setitem(
        EXAMPLES, "grade_gist", {**EXAMPLES["grade_gist"], "covered_points": ["kp6"]}
    )
    gateway, _ = make_gateway(fake_accounting)
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway))
    assert report["status"] == "fail"
    assert report["successful_attempts"] == 0


def test_oversized_learner_text_is_refused_before_admission(fake_accounting):
    data = gist_dataset().model_dump(mode="json")
    data["cases"][0]["input"]["gist"] = "x" * 9000
    gateway, calls = make_gateway(fake_accounting)
    report = asyncio.run(run(Dataset.model_validate(data), thresholds(), gateway))
    assert report["status"] == "fail"
    assert calls == []
    assert fake_accounting.calls == []


def test_reference_trimming_is_recorded(fake_accounting):
    data = gist_dataset().model_dump(mode="json")
    data["cases"][0]["input"]["transcript"] = "A reference sentence. " * 1000
    gateway, _ = make_gateway(fake_accounting)
    report = asyncio.run(run(Dataset.model_validate(data), thresholds(), gateway))
    assert report["status"] == "pass"
    assert report["cases"][0]["runs"][0]["trimmed"] == ["transcript"]


def test_optional_diagnostic_metrics_do_not_require_calibration(fake_accounting):
    config = thresholds()
    for name in [
        "mae.overall",
        "max_range.main_idea",
        "max_range.key_details",
        "max_range.accuracy",
    ]:
        del config.rules["gist"][name]
    gateway, _ = make_gateway(fake_accounting)
    assert asyncio.run(run(gist_dataset(), config, gateway))["status"] == "pass"


def test_synthetic_limits_cannot_evaluate_teacher_manifest(fake_accounting):
    gateway, calls = make_gateway(fake_accounting)
    dataset = gist_dataset().model_copy(update={"kind": "teacher"})
    report = asyncio.run(run(dataset, thresholds(), gateway))
    assert report["status"] == "unconfigured"
    assert calls == []


def test_task_override_is_identified_as_requested_provider(fake_accounting):
    gateway, calls = make_gateway(fake_accounting, ("a", "b"))
    gateway._config.tasks["grade_gist"] = ("b",)
    report = asyncio.run(run(gist_dataset(), thresholds(), gateway, task_provider="b"))
    assert report["requested_provider"] == "b"
    assert report["role_provider"] == "a"
    assert report["task"] == "grade_gist"
    assert calls == ["b"] * 3


def test_missing_synthetic_shadow_samples_fail_report(fake_accounting):
    data = json.loads((ROOT / "ai-evals/fixtures/shadow.json").read_text())
    del data["cases"][0]["synthetic_runs"]
    config = Thresholds.model_validate_json((ROOT / "ai-evals/smoke.thresholds.json").read_text())
    gateway, calls = make_gateway(fake_accounting)
    report = asyncio.run(
        run(Dataset.model_validate(data), config, gateway, offline=True, smoke=True)
    )
    assert report["status"] == "fail"
    assert report["successful_attempts"] == 0
    assert report["reason"] == "incomplete_run"
    assert len(report["cases"][0]["runs"]) == 3
    assert calls == []
