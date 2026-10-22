import pytest

from listenup.ai.evals.metrics import summarize
from listenup.ai.evals.models import Grade


def test_teacher_agreement_and_mae():
    expected = Grade(scores={"main_idea": 80, "accuracy": 100}, overall=84, level="Good")
    runs = [
        Grade(scores={"main_idea": 70, "accuracy": 100}, overall=79, level="Good"),
        Grade(scores={"main_idea": 80, "accuracy": 90}, overall=82, level="Good"),
        Grade(scores={"main_idea": 90, "accuracy": 80}, overall=85, level="Excellent"),
    ]
    result = summarize([(expected, runs)])
    assert result["mae.main_idea"] == pytest.approx(20 / 3)
    assert result["mae.accuracy"] == 10
    assert result["level_agreement"] == pytest.approx(2 / 3)
    assert result["mae.overall"] == pytest.approx(8 / 3)


def test_three_run_consistency_uses_worst_case_range():
    expected = Grade(scores={"timing": 50}, overall=50, filler_count=2)
    runs = [
        Grade(scores={"timing": n}, overall=n, filler_count=f)
        for n, f in [(45, 1), (50, 2), (56, 4)]
    ]
    result = summarize([(expected, runs)])
    assert result["max_range.timing"] == 11
    assert result["max_range.overall"] == 11
    assert result["filler_count_mae"] == 1


def test_missing_runs_or_scores_cannot_look_like_perfect_results():
    grade = Grade(scores={"timing": 50}, overall=50)
    for rows in [[], [(grade, [])], [(grade, [grade] * 2)]]:
        with pytest.raises(ValueError):
            summarize(rows)
    with pytest.raises(ValueError):
        summarize([(grade, [Grade(scores={"accent": 50}, overall=50)] * 3)])


@pytest.mark.parametrize("score", [-1, 101, float("nan"), float("inf")])
def test_invalid_numeric_scores_are_rejected(score):
    with pytest.raises(ValueError):
        Grade(scores={"timing": score}, overall=50)
