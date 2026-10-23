import json
import sys
from pathlib import Path

import pytest

from listenup_spikes.compare import _row, incomplete_windows, main
from listenup_spikes.metrics import boundary_errors_ms


def test_large_timing_errors_are_measured_and_fail_the_gate() -> None:
    labelled = [("alpha", 0.0, 0.2), ("beta", 2.0, 2.2)]
    predicted = [("alpha", 0.0, 0.2), ("beta", 3.5, 3.7)]
    errors = boundary_errors_ms(predicted, labelled)
    assert errors == pytest.approx([0, 0, 1500, 1500])
    row = _row("example", errors, 2, hand_labels=True)
    assert row["mean_ms"] == 750
    assert row["within_50ms"] == 0.5
    assert row["meets_hand_label_gate"] is False


def test_timestamps_do_not_select_a_better_matching_repeated_word() -> None:
    labelled = [("the", 0.0, 0.2), ("cat", 0.2, 0.4)]
    predicted = [("the", 0.0, 0.2), ("dog", 0.2, 0.4), ("the", 5.0, 5.2), ("cat", 5.2, 5.4)]
    assert boundary_errors_ms(predicted, labelled) == pytest.approx([5000] * 4)


@pytest.mark.parametrize("errors,words", [([], 0), ([], 2), ([0.0, 0.0], 2)])
def test_incomplete_or_empty_comparisons_cannot_pass(errors: list[float], words: int) -> None:
    row = _row("example", errors, words, hand_labels=True)
    assert row["words_unmatched"] == words - len(errors) // 2
    assert row["meets_hand_label_gate"] is False
    assert row["within_50ms"] == (0.5 if errors else 0.0)
    if not errors:
        assert row["mean_ms"] is None


def test_gate_uses_unrounded_mean_and_requires_hand_labels() -> None:
    assert _row("example", [50, 50], 1, hand_labels=True)["meets_hand_label_gate"] is True
    assert _row("example", [50.01, 50.01], 1, hand_labels=True)["meets_hand_label_gate"] is False
    assert "meets_hand_label_gate" not in _row("agreement", [0, 0], 1)


def _windows(labels: Path, **passages: float) -> None:
    """windows.json with one window per passage, from 0 s for the given seconds."""
    spec = {
        f"w-{passage}": {"passage": passage, "start_s": 0, "seconds": seconds}
        for passage, seconds in passages.items()
    }
    (labels / "windows.json").write_text(json.dumps({"windows": spec}))


def _compare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str, source: bool = True
) -> dict[str, object]:
    words = tmp_path / "words"
    words.mkdir(exist_ok=True)
    if source:
        (words / "model").mkdir(exist_ok=True)
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["spike-compare", str(words), "--labels", str(tmp_path / "labels"), "--out", str(out)]
        + list(extra),
    )
    main()
    report: dict[str, object] = json.loads((out / "spike-19-b2-boundaries.json").read_text())
    return report


def _model(tmp_path: Path, passage: str, words: list[tuple[str, float, float]]) -> None:
    folder = tmp_path / "words" / "model"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"window": [0, 100], "words": [{"word": w, "start": s, "end": e} for w, s, e in words]}
    (folder / f"{passage}.json").write_text(json.dumps(data))


@pytest.fixture
def labels(tmp_path: Path) -> Path:
    folder = tmp_path / "labels"
    folder.mkdir()
    return folder


def test_report_counts_missing_passages_and_zero_matches(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "present", [("wrong", 0, 1)])
    _windows(labels, present=2, missing=4)
    (labels / "present.labels.csv").write_text("hello,0,1\n")
    (labels / "missing.labels.csv").write_text("world,2,3\n")
    row = _compare(tmp_path, monkeypatch)["rows"][0]
    assert row["words_compared"] == row["words_unmatched"] == 2
    assert row["words_matched"] == 0
    assert row["meets_hand_label_gate"] is False


def test_empty_label_directory_reports_a_failed_gate(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _windows(labels, todo=10)
    report = _compare(tmp_path, monkeypatch)
    assert report["summary"]["hand-labelled windows"] == 0
    assert report["summary"]["incomplete windows"] == "w-todo"
    assert report["rows"][0]["meets_hand_label_gate"] is False


def test_unlabelled_windows_fail_the_gate_and_are_listed(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "done", [("hello", 0, 1)])
    _windows(labels, done=2, todo=10)
    (labels / "done.labels.csv").write_text("hello,0,1\n")
    report = _compare(tmp_path, monkeypatch)
    assert report["summary"]["incomplete windows"] == "w-todo"
    row = report["rows"][0]
    assert row["mean_ms"] == 0
    assert row["meets_hand_label_gate"] is False


def test_every_window_fully_labelled_and_matched_passes(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "a", [("one", 0.5, 1.0), ("two", 1.0, 1.5)])
    _model(tmp_path, "b", [("three", 0.2, 1.8)])
    _windows(labels, a=2, b=2)
    (labels / "a.labels.csv").write_text("one,0.5,1.0\ntwo,1.0,1.5\n")
    (labels / "b.labels.csv").write_text("three,0.2,1.8\n")
    report = _compare(tmp_path, monkeypatch)
    assert report["summary"]["incomplete windows"] == "none"
    assert report["summary"]["hand-labelled windows"] == 2
    assert report["rows"][0]["meets_hand_label_gate"] is True


def test_a_window_with_an_empty_label_file_is_listed(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "a", [("one", 0, 1)])
    _windows(labels, a=1, b=1)
    (labels / "a.labels.csv").write_text("one,0,1\n")
    (labels / "b.labels.csv").write_text("")
    report = _compare(tmp_path, monkeypatch)
    assert report["summary"]["incomplete windows"] == "w-b"
    assert report["rows"][0]["meets_hand_label_gate"] is False


def test_partly_labelled_window_fails_the_gate(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One word labelled in a 60 s window: the rest of the window is unlabelled.
    _model(tmp_path, "a", [("one", 0, 1)])
    _windows(labels, a=60)
    (labels / "a.labels.csv").write_text("one,0,1\n")
    report = _compare(tmp_path, monkeypatch)
    assert report["summary"]["incomplete windows"] == "w-a"
    assert report["rows"][0]["meets_hand_label_gate"] is False


@pytest.mark.parametrize(
    "rows,complete",
    [
        ([("a", 2.0, 3.0), ("b", 3.0, 7.0), ("c", 7.0, 9.0)], True),  # edge gaps 2 s and 1 s
        ([("a", 3.5, 4.0), ("b", 4.0, 10.0)], False),  # 3.5 s before the first word
        ([("a", 0.0, 1.0), ("b", 5.0, 10.0)], False),  # 4 s unlabelled in the middle
        ([("a", 0.0, 1.0), ("<pause>", 1.0, 5.0), ("b", 5.0, 10.0)], True),  # marked pause
        ([("a", 0.0, 6.5)], False),  # 3.5 s unlabelled at the end
        ([("<pause>", 0.0, 10.0)], False),  # no words at all
    ],
)
def test_window_coverage_allows_gaps_up_to_three_seconds(
    rows: list[tuple[str, float, float]], complete: bool
) -> None:
    windows = {"w": ("p", 0.0, 10.0)}
    assert incomplete_windows(windows, {"p": rows}) == ([] if complete else ["w"])


def test_pause_markers_are_not_compared_as_words(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "a", [("one", 0, 1), ("two", 4, 5)])
    _windows(labels, a=5)
    (labels / "a.labels.csv").write_text("one,0,1\n<pause>,1,4\ntwo,4,5\n")
    row = _compare(tmp_path, monkeypatch)["rows"][0]
    assert row["words_compared"] == 2
    assert row["meets_hand_label_gate"] is True


def test_hand_label_comparison_requires_the_window_spec(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "a", [("one", 0, 1)])
    (labels / "a.labels.csv").write_text("one,0,1\n")
    with pytest.raises(SystemExit, match="windows.json"):
        _compare(tmp_path, monkeypatch)


def test_duplicate_window_passages_are_refused(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {
        "x": {"passage": "a", "start_s": 0, "seconds": 1},
        "y": {"passage": "a", "start_s": 5, "seconds": 1},
    }
    (labels / "windows.json").write_text(json.dumps({"windows": spec}))
    with pytest.raises(SystemExit, match="passage a"):
        _compare(tmp_path, monkeypatch)


def test_only_restricts_the_windows_checked(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(tmp_path, "a", [("one", 0, 1)])
    _windows(labels, a=1, b=1)
    (labels / "a.labels.csv").write_text("one,0,1\n")
    report = _compare(tmp_path, monkeypatch, "--only", "a")
    assert report["summary"]["incomplete windows"] == "none"
    assert report["rows"][0]["meets_hand_label_gate"] is True


def test_no_model_output_still_reports_a_failed_gate(
    tmp_path: Path, labels: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _windows(labels, a=1)
    (labels / "a.labels.csv").write_text("one,0,1\n")
    report = _compare(tmp_path, monkeypatch, source=False)
    [row] = report["rows"]
    assert row["comparison"] == "no model output vs hand labels"
    assert row["words_compared"] == row["words_unmatched"] == 1
    assert row["meets_hand_label_gate"] is False
