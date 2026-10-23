"""Rubric arithmetic is application code, never provider arithmetic (#68)."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from listenup.modules.grading.domain.scoring import Rubric


def test_rubric_weights_are_loaded(tmp_path):
    path = tmp_path / "rubric.json"
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "weights": {"main_idea": 50, "key_details": 30, "accuracy": 20},
                "levels": {"fair": 50, "good": 70, "excellent": 90},
            }
        )
    )
    rubric = Rubric.load(path)
    assert rubric.score({"main_idea": 100, "key_details": 0, "accuracy": 50}) == 60
    data = json.loads(path.read_text())
    data["weights"] = {"main_idea": 20, "key_details": 30, "accuracy": 50}
    path.write_text(json.dumps(data))
    assert Rubric.load(path).score({"main_idea": 100, "key_details": 0, "accuracy": 50}) == 45


@pytest.mark.parametrize(
    "scores",
    [
        {"main_idea": -1, "key_details": 0, "accuracy": 0},
        {"main_idea": 101, "key_details": 0, "accuracy": 0},
        {"main_idea": True, "key_details": 0, "accuracy": 0},
        {"main_idea": 50, "key_details": 0},
    ],
)
def test_invalid_dimension_scores_are_rejected(scores, tmp_path):
    path = tmp_path / "rubric.json"
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "weights": {"main_idea": 50, "key_details": 30, "accuracy": 20},
                "levels": {"fair": 50, "good": 70, "excellent": 90},
            }
        )
    )
    with pytest.raises(ValueError):
        Rubric.load(path).score(scores)


@pytest.fixture
def rubric():
    from listenup.ai.prompt_files import PROMPTS_DIR

    return Rubric.load(PROMPTS_DIR / "grade_gist" / "v2.rubric.json")


@pytest.mark.parametrize(
    "score, expected",
    [
        (0, "needs_work"),
        (49, "needs_work"),
        (50, "fair"),
        (69, "fair"),
        (70, "good"),
        (89, "good"),
        (90, "excellent"),
        (100, "excellent"),
    ],
)
def test_level_boundaries(rubric, score, expected):
    assert rubric.level(score) == expected


@pytest.mark.parametrize("score", [-1, 101, True])
def test_invalid_overall_rejected(rubric, score):
    with pytest.raises(ValueError):
        rubric.level(score)


def test_rounding_is_half_up(rubric):
    assert rubric.score({"main_idea": 95, "key_details": 100, "accuracy": 100}) == 98
    assert rubric.score({"main_idea": 94, "key_details": 100, "accuracy": 100}) == 97


@pytest.mark.parametrize(
    "change",
    [
        {"weights": {"main_idea": 50, "key_details": 30, "accuracy": 19}},
        {"weights": {"main_idea": 50, "key_details": 50, "accuracy": 0}},
        {"weights": {"main_idea": True, "key_details": 79, "accuracy": 20}},
        {"levels": {"fair": 70, "good": 50, "excellent": 90}},
        {"levels": {"fair": 50, "good": 70, "excellent": 101}},
        {"version": ""},
    ],
)
def test_invalid_rubric_configuration_rejected(rubric, tmp_path, change):
    data = {
        "version": rubric.version,
        "weights": dict(rubric.weights),
        "levels": dict(rubric.levels),
        **change,
    }
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Rubric.load(path)


@given(st.integers(0, 100), st.integers(0, 100), st.integers(0, 100))
def test_weighted_score_stays_between_dimension_extremes(main, details, accuracy):
    rubric = Rubric(
        "test",
        {"main_idea": 50, "key_details": 30, "accuracy": 20},
        {"fair": 50, "good": 70, "excellent": 90},
    )
    score = rubric.score({"main_idea": main, "key_details": details, "accuracy": accuracy})
    assert min(main, details, accuracy) <= score <= max(main, details, accuracy)
