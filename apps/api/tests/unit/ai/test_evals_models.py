import copy

import pytest

from listenup.ai.evals.models import Dataset, Rule, Thresholds
from tests.unit.ai.test_evals_runner import gist_dataset, thresholds


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_id",
        "missing_dimension",
        "extra_dimension",
        "wrong_input",
        "no_level",
        "recorded_gist",
    ],
)
def test_invalid_manifests_are_rejected(change):
    data = gist_dataset().model_dump(mode="json")
    case = data["cases"][0]
    if change == "duplicate_id":
        data["cases"].append(copy.deepcopy(case))
    elif change == "missing_dimension":
        del case["expected"]["scores"]["accuracy"]
    elif change == "extra_dimension":
        case["expected"]["scores"]["unexpected"] = 5
    elif change == "wrong_input":
        case["input"] = {"recording": "r", "reference_audio": "a", "reference_text": "t"}
    elif change == "no_level":
        case["expected"]["level"] = None
    else:
        case["synthetic_runs"] = [case["expected"]] * 3
    with pytest.raises(ValueError):
        Dataset.model_validate(data)


@pytest.mark.parametrize(
    "rule", [{}, {"min": 0, "max": 1}, {"min": float("nan")}, {"max": float("inf")}]
)
def test_invalid_thresholds_are_rejected(rule):
    with pytest.raises(ValueError):
        Rule.model_validate(rule)


def test_level_boundaries_must_be_ordered():
    data = thresholds().model_dump()
    data["gist_level_bounds"] = [60, 40, 90]
    with pytest.raises(ValueError):
        Thresholds.model_validate(data)


def test_production_thresholds_preserve_only_existing_requirements():
    from tests.unit.ai.test_evals_runner import ROOT

    config = Thresholds.model_validate_json((ROOT / "ai-evals/thresholds.json").read_text())
    assert config.gist_level_bounds is None
    assert config.rules["gist"]["max_range.overall"].max == 10
    assert config.rules["shadow"]["max_range.timing"].max == 10
    assert config.rules["shadow"]["filler_count_max_error"].max == 1
    assert not any(name.startswith("mae.") for rules in config.rules.values() for name in rules)


def test_shadow_requires_filler_counts():
    import json

    from tests.unit.ai.test_evals_runner import ROOT

    data = json.loads((ROOT / "ai-evals/fixtures/shadow.json").read_text())
    del data["cases"][0]["expected"]["filler_count"]
    with pytest.raises(ValueError, match="Shadow requires filler counts"):
        Dataset.model_validate(data)
