import json
import sys
from pathlib import Path

import pytest

from listenup_spikes.compare import _row, main
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


def test_report_counts_missing_passages_and_zero_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "words" / "model"
    source.mkdir(parents=True)
    (source / "present.json").write_text(
        json.dumps({"window": [0, 10], "words": [{"word": "wrong", "start": 0, "end": 1}]})
    )
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "present.labels.csv").write_text("hello,0,1\n")
    (labels / "missing.labels.csv").write_text("world,2,3\n")
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["spike-compare", str(source.parent), "--labels", str(labels), "--out", str(out)],
    )
    main()
    report = json.loads((out / "spike-19-b2-boundaries.json").read_text())
    row = report["rows"][0]
    assert row["words_compared"] == row["words_unmatched"] == 2
    assert row["words_matched"] == 0
    assert row["meets_hand_label_gate"] is False


def test_empty_label_directory_reports_a_failed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "words" / "model"
    source.mkdir(parents=True)
    labels = tmp_path / "labels"
    labels.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["spike-compare", str(source.parent), "--labels", str(labels), "--out", str(out)],
    )
    main()
    report = json.loads((out / "spike-19-b2-boundaries.json").read_text())
    assert report["summary"]["hand-labelled windows"] == 0
    assert report["rows"][0]["meets_hand_label_gate"] is False
