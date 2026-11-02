"""spike-b4 (#22): reading the data folder and summarizing a setting."""

import json
from pathlib import Path

from listenup_spikes.b4_fillers import load_items, summarize_setting
from listenup_spikes.metrics import FillerCounts, FillerMark


def test_load_items_reads_counts_and_timed_marks_when_present(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "a.fillers").write_text("2\n")
    (tmp_path / "a.marks.json").write_text(
        json.dumps(
            [
                {"start": 1.0, "end": 1.2, "kind": "hesitation", "text": "uh"},
                {"start": 3.0, "end": 3.4, "kind": "discourse", "text": "you know"},
            ]
        )
    )
    (tmp_path / "b.wav").write_bytes(b"")
    (tmp_path / "b.fillers").write_text("4\n")  # a teacher count only: no times
    (tmp_path / "c.wav").write_bytes(b"")  # no .fillers: not a B4 item
    items = load_items(tmp_path)
    assert [(i.audio.name, i.true_count) for i in items] == [("a.wav", 2), ("b.wav", 4)]
    assert items[0].marks == [
        FillerMark(1.0, 1.2, "hesitation", "uh"),
        FillerMark(3.0, 3.4, "discourse", "you know"),
    ]
    assert items[1].marks is None


def test_summarize_setting_pools_recordings_per_kind_and_checks_the_target() -> None:
    recordings = [
        {
            "hesitation": FillerCounts(8, 2, 1),
            "discourse": FillerCounts(1, 1, 3),
            "all": FillerCounts(9, 3, 4),
        },
        {
            "hesitation": FillerCounts(8, 0, 0),
            "discourse": FillerCounts(0, 0, 2),
            "all": FillerCounts(8, 0, 2),
        },
    ]
    summary = summarize_setting("plain", recordings)
    assert summary["plain recall"] == round(17 / 20, 3)
    assert summary["plain precision"] == round(17 / 23, 3)
    assert summary["plain hesitation recall"] == round(16 / 18, 3)
    assert summary["plain discourse recall"] == 0.5
    assert summary["plain discourse precision"] == round(1 / 6, 3)
    assert summary["plain meets 80% recall"] is True
    assert (
        summarize_setting(
            "p",
            [
                {
                    "hesitation": FillerCounts(3, 2, 0),
                    "discourse": FillerCounts(0, 0, 0),
                    "all": FillerCounts(3, 2, 0),
                }
            ],
        )["p meets 80% recall"]
        is False
    )
    assert (
        summarize_setting(
            "p",
            [
                {
                    "hesitation": FillerCounts(0, 0, 0),
                    "discourse": FillerCounts(0, 0, 0),
                    "all": FillerCounts(0, 0, 0),
                }
            ],
        )["p discourse recall"]
        is None
    )
