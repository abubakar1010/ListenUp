"""Evaluate through public gateway calls; a synthetic report is never activation evidence."""

from typing import Any

from listenup.ai.errors import AIUnavailable
from listenup.ai.evals.metrics import summarize
from listenup.ai.evals.models import Dataset, Grade, Thresholds
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Role
from listenup.ai.tasks import GistGrade, GradeGistInput
from listenup.ai.text_tasks import run_task


def required_metrics(dataset: Dataset) -> set[str]:
    names = set(dataset.cases[0].expected.scores)
    if dataset.suite == "gist":
        return {f"mae.{name}" for name in names} | {"level_agreement", "max_range.overall"}
    return {f"{metric}.{name}" for metric in ("mae", "max_range") for name in names} | {
        "filler_count_max_error"
    }


def available_metrics(dataset: Dataset) -> set[str]:
    names = set(dataset.cases[0].expected.scores) | {"overall"}
    return {f"{metric}.{name}" for metric in ("mae", "max_range") for name in names} | (
        {"level_agreement"}
        if dataset.suite == "gist"
        else {"filler_count_mae", "filler_count_max_error"}
    )


def gist_grade(value: GistGrade, bounds: tuple[float, float, float]) -> Grade:
    # Existing SRS 5.2.1 weights, not calibration choices. Level cutoffs are supplied.
    scores = value.dimension_scores
    overall = (50 * scores.main_idea + 30 * scores.key_details + 20 * scores.accuracy) / 100
    levels = ("Needs work", "Fair", "Good", "Excellent")
    return Grade.model_validate(
        {
            "scores": scores.model_dump(),
            "overall": overall,
            "level": levels[sum(overall >= b for b in bounds)],
        }
    )


async def run(
    dataset: Dataset,
    thresholds: Thresholds,
    gateway: AIGateway,
    *,
    smoke: bool = False,
    offline: bool = False,
    task_provider: str | None = None,
) -> dict[str, Any]:
    selected = [case for case in dataset.cases if not smoke or case.smoke]
    role = Role.TEXT_AI if dataset.suite == "gist" else Role.SPEECH_ASSESSMENT
    try:
        requested = gateway.entry(role).provider
    except AIUnavailable:
        requested = None
    report: dict[str, Any] = {
        "version": 1,
        "dataset_id": dataset.id,
        "dataset_kind": dataset.kind,
        "suite": dataset.suite,
        "execution": "gateway" if dataset.suite == "gist" else "unavailable",
        "notice": (
            "Synthetic fixtures: harness validation only, not model quality."
            if dataset.kind == "synthetic"
            else "Teacher-reference evaluation; inspect provenance and coverage before activation."
        ),
        "model_quality_evidence": False,
        "provider_acceptance": False,
        "requested_provider": task_provider or requested,
        "role_provider": requested,
        "role": role.value,
        "task": "grade_gist" if dataset.suite == "gist" else "assess",
        "actual_providers": [],
        "selected_cases": len(selected),
        "attempts": 0,
        "successful_attempts": 0,
        "cases": [],
        "metrics": {},
        "thresholds": {},
        "status": "fail",
        "reason": None,
    }
    if not selected:
        report["reason"] = "empty_selection"
        return report
    if offline and dataset.kind != "synthetic":
        report.update(status="unavailable", reason="offline_requires_synthetic_dataset")
        return report
    if dataset.suite == "shadow" and not (offline and dataset.kind == "synthetic"):
        report.update(status="unavailable", reason="shadow_scoring_service_unavailable")
        return report
    rules = thresholds.rules.get(dataset.suite, {})
    if (
        thresholds.scope != dataset.kind
        or not required_metrics(dataset) <= set(rules) <= available_metrics(dataset)
        or (dataset.suite == "gist" and thresholds.gist_level_bounds is None)
    ):
        report.update(status="unconfigured", reason="missing_or_incompatible_thresholds")
        return report
    rows = []
    actual: set[str] = set()
    for case in selected:
        runs: list[dict[str, Any]] = []
        grades: list[Grade] = []
        for repetition in range(3):
            report["attempts"] += 1
            observation: dict[str, Any] = {
                "repetition": repetition + 1,
                "grade": None,
                "error": None,
                "provenance": None,
                "prompt_version": None,
                "trimmed": [],
            }
            try:
                if dataset.suite == "shadow":
                    report["execution"] = "synthetic_report_contract"
                    if case.synthetic_runs is None:
                        raise ValueError("missing synthetic samples")
                    grade = case.synthetic_runs[repetition]
                else:
                    assert isinstance(case.input, GradeGistInput)
                    assert thresholds.gist_level_bounds is not None
                    output = await run_task(
                        gateway,
                        "grade_gist",
                        case.input.model_dump(mode="json"),
                        GistGrade,
                        context=case.context,
                    )
                    result = output.result
                    if not set(result.value.covered_points) <= {
                        p.id for p in case.input.key_points
                    }:
                        raise ValueError("unknown covered point")
                    grade = gist_grade(result.value, thresholds.gist_level_bounds)
                    observation.update(
                        provenance=result.provenance.model_dump(),
                        prompt_version=result.prompt_version,
                        trimmed=list(output.trimmed),
                    )
                    actual.add(result.provenance.provider)
                grades.append(grade)
                observation["grade"] = grade.model_dump()
                report["successful_attempts"] += 1
            except AIUnavailable:
                observation["error"] = "gateway_unavailable"
            except ValueError:
                # Never serialize input validation errors, which can contain private text.
                observation["error"] = "invalid_evaluation_input_or_output"
            runs.append(observation)
        report["cases"].append(
            {"id": case.id, "expected": case.expected.model_dump(), "runs": runs}
        )
        rows.append((case.expected, grades))
    report["actual_providers"] = sorted(actual)
    if report["successful_attempts"] != report["attempts"]:
        report["reason"] = "incomplete_run"
        return report
    metrics = summarize(rows)
    report["metrics"] = metrics
    decisions = {
        name: {
            **rule.model_dump(exclude_none=True),
            "actual": metrics[name],
            "pass": (
                metrics[name] >= rule.min
                if rule.min is not None
                else rule.max is not None and metrics[name] <= rule.max
            ),
        }
        for name, rule in rules.items()
    }
    report["thresholds"] = decisions
    report["status"] = "pass" if all(d["pass"] for d in decisions.values()) else "fail"
    report["model_quality_evidence"] = (
        dataset.kind == "teacher" and not offline and "fake" not in actual
    )
    if "fake" in actual:
        report["notice"] = "Fake-provider fixtures: harness validation only, not model quality."
    report["provider_acceptance"] = (
        report["status"] == "pass"
        and report["model_quality_evidence"]
        and not smoke
        and actual == {task_provider or requested}
    )
    return report
