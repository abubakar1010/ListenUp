"""Output formats of the Text AI tasks (NFR-AI-4): anything out of range is rejected."""

import copy

import pytest
from pydantic import ValidationError

from listenup.ai.tasks import EXAMPLES, TASK_MODELS, GistGrade, KeyPoints, ShadowFeedback


@pytest.mark.parametrize("task", sorted(TASK_MODELS))
def test_example_output_is_valid(task):
    assert TASK_MODELS[task].model_validate(EXAMPLES[task])


def kp(*kinds):
    return {"key_points": [{"text": f"Point number {i}.", "kind": k} for i, k in enumerate(kinds)]}


@pytest.mark.parametrize(
    "kinds",
    [
        ("main", "supporting"),
        ("main",) + ("supporting",) * 6,
        ("supporting", "main", "supporting"),
        ("main", "main", "supporting"),
        ("supporting", "supporting", "supporting"),
    ],
)
def test_key_points_need_three_to_six_with_one_main_idea_first(kinds):
    with pytest.raises(ValidationError):
        KeyPoints.model_validate(kp(*kinds))


def test_key_points_accept_the_boundaries():
    assert len(KeyPoints.model_validate(kp("main", "supporting", "supporting")).key_points) == 3
    assert len(KeyPoints.model_validate(kp("main", *["supporting"] * 5)).key_points) == 6


def grade(**change):
    data = copy.deepcopy(EXAMPLES["grade_gist"])
    for path, value in change.items():
        target = data
        *parents, leaf = path.split("__")
        for parent in parents:
            target = target[parent]
        target[leaf] = value
    return data


@pytest.mark.parametrize(
    "change",
    [
        {"dimension_scores__main_idea": 101},
        {"dimension_scores__accuracy": -1},
        {"dimension_scores__key_details": "80"},
        {"dimension_scores__key_details": 80.5},
        {"overall": 90},  # our code computes the overall score, never the model
        {"covered_points": ["kp1", "kp1"]},
        {"wrong_claims": ["x"] * 6},
        {"feedback": ""},
        {"feedback": "x" * 1501},
    ],
)
def test_gist_grade_rejects_out_of_range_or_extra_output(change):
    with pytest.raises(ValidationError):
        GistGrade.model_validate(grade(**change))


def test_gist_grade_accepts_the_boundaries():
    GistGrade.model_validate(
        grade(
            dimension_scores__main_idea=0,
            dimension_scores__accuracy=100,
            covered_points=[],
            feedback="x" * 1500,
        )
    )


@pytest.mark.parametrize("fixes", [[], ["a", "b", "c", "d"]])
def test_shadow_feedback_needs_one_to_three_fixes(fixes):
    with pytest.raises(ValidationError):
        ShadowFeedback.model_validate({"feedback": "Good.", "top_fixes": fixes})
