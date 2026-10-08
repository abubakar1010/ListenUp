"""Pure helpers of the B1/B2 harness: passage building, trimming, windows, label files."""

import json
from pathlib import Path

import numpy as np
import pytest

from listenup_spikes import product
from listenup_spikes.align import CONTEXT_S, FRAME_SAMPLES, SAMPLE_RATE, window_bounds
from listenup_spikes.b1_transcribe import trim_to_window
from listenup_spikes.compare import load_labels
from listenup_spikes.datasets import (
    Utterance,
    alternate_by_sex,
    assemble,
    choose_span,
    voxpopuli_debates,
)
from listenup_spikes.labelkit import import_labels, read_tier, textgrid, window_hint
from listenup_spikes.metrics import boundary_errors_ms, spread


def utterance(uid: str, seconds: float, value: float = 0.0) -> Utterance:
    return Utterance(uid, uid, np.full(round(seconds * SAMPLE_RATE), value, dtype=np.float32))


def test_choose_span_needs_padding_on_both_sides() -> None:
    # 3 s of audio before is not enough padding, so the passage starts after 6 s.
    assert choose_span([3, 3, 100, 90, 10], target_s=180) == (2, 4)
    assert choose_span([3, 3, 100, 90, 4], target_s=180) is None  # 4 s after: too short
    assert choose_span([100, 100], target_s=180) is None


def test_assemble_cuts_five_seconds_of_neighbours_and_records_segment_times() -> None:
    parts = [utterance("a", 8, 1), utterance("b", 3, 2), utterance("c", 4, 3), utterance("d", 9, 4)]
    audio, layout = assemble(parts, 1, 3)
    assert len(audio) == round(17 * SAMPLE_RATE)  # 5 + 3 + 4 + 5
    assert audio[0] == 1 and audio[-1] == 4
    assert layout["pad_before_s"] == 5.0 and layout["passage_s"] == 7.0
    assert layout["segments"] == [
        {"id": "b", "start": 5.0, "end": 8.0, "text": "b"},
        {"id": "c", "start": 8.0, "end": 12.0, "text": "c"},
    ]


def test_alternate_by_sex_balances_any_prefix() -> None:
    sexes = {"1": "M", "2": "F", "3": "M", "4": "F", "5": "M"}
    assert alternate_by_sex(list(sexes), sexes) == ["2", "1", "4", "3", "5"]


def test_voxpopuli_debates_order_speeches_then_segments() -> None:
    rows = [
        {"audio_id": "D1-en_20090101-10:05:00_1"},
        {"audio_id": "D1-en_20090101-10:00:00_10"},
        {"audio_id": "D1-en_20090101-10:00:00_2"},
        {"audio_id": "D2-en_20090101-11:00:00_0"},
    ]
    debates = voxpopuli_debates(rows)
    assert [r["audio_id"] for r in debates["D1-en"]] == [
        "D1-en_20090101-10:00:00_2",
        "D1-en_20090101-10:00:00_10",
        "D1-en_20090101-10:05:00_1",
    ]
    assert list(debates) == ["D1-en", "D2-en"]


def test_trim_to_window_keeps_words_whose_midpoint_is_inside() -> None:
    words = [("pad", 4.0, 4.9), ("edge", 4.8, 5.4), ("in", 6.0, 6.2), ("out", 9.8, 10.4)]
    assert [w[0] for w in trim_to_window(words, 5.0, 10.0)] == ["edge", "in"]


def test_window_bounds_cover_the_audio_with_context_in_whole_frames() -> None:
    n = 75 * SAMPLE_RATE + 123
    bounds = window_bounds(n, 30)
    assert [(s, e) for s, e, _, _ in bounds][0] == (0, 30 * SAMPLE_RATE)
    assert bounds[-1][1] == n
    assert all(b[0] == a[1] for a, b in zip(bounds, bounds[1:], strict=False))
    context = round(CONTEXT_S * SAMPLE_RATE)
    for start, end, in_start, in_end in bounds:
        assert (start - in_start) % FRAME_SAMPLES == 0
        assert in_start == max(0, start - context) and in_end == min(n, end + context)


def test_boundary_errors_match_by_text_and_time() -> None:
    predicted = [("the", 1.0, 1.2), ("cat", 1.25, 1.6), ("the", 30.0, 30.2), ("dog", 30.3, 30.6)]
    labelled = [("the", 30.05, 30.2), ("dog", 30.3, 30.7), ("bird", 31.0, 31.5)]
    errors = boundary_errors_ms(predicted, labelled)
    # "the" matches the one at 30 s, not the first; "bird" has no match and is skipped.
    assert errors == pytest.approx([50, 0, 0, 100])


def test_spread_reports_median_and_shares() -> None:
    s = spread([10, 20, 30, 200])
    assert (s.median, s.share_within_50ms, s.share_within_100ms) == (25, 0.75, 0.75)


def test_textgrid_round_trips_the_words_tier() -> None:
    grid = textgrid(60.0, 'he said "hi"')
    assert read_tier(grid, "hint") == [('he said "hi"', 0.0, 60.0)]
    assert read_tier(grid, "words") == []
    labelled = grid.replace(
        'name = "words"\n        xmin = 0\n        xmax = 60.0\n        intervals: size = 1\n'
        "        intervals [1]:\n            xmin = 0\n            xmax = 60.0\n"
        '            text = ""',
        'name = "words"\n        xmin = 0\n        xmax = 60.0\n        intervals: size = 3\n'
        "        intervals [1]:\n            xmin = 0\n            xmax = 0.5\n"
        '            text = ""\n'
        "        intervals [2]:\n            xmin = 0.5\n            xmax = 0.9\n"
        '            text = "hello"\n'
        "        intervals [3]:\n            xmin = 0.9\n            xmax = 60.0\n"
        '            text = ""',
    )
    assert read_tier(labelled, "words") == [("hello", 0.5, 0.9)]


def test_window_hint_uses_overlapping_segments_only() -> None:
    segments = [
        {"start": 0.0, "end": 5.0, "text": "one"},
        {"start": 5.0, "end": 9.0, "text": "two"},
        {"start": 9.0, "end": 12.0, "text": "three"},
    ]
    assert window_hint(segments, 4.0, 9.0) == "one two"


needs_product = pytest.mark.skipif(
    not product.available(), reason="set PYTHONPATH=../apps/api/src for the Dictation rules"
)


@needs_product
def test_dictation_wer_counts_numbers_and_spellings_as_equal() -> None:
    assert product.dictation_wer("in two thousand and ten the colour", "in 2010 the color").wer == 0
    assert product.dictation_wer("the cat sat", "the hat sat").substitutions == 1


@needs_product
def test_false_marks_blame_the_learner_for_transcript_errors() -> None:
    machine = [("the", 0.0, 0.2), ("hat", 0.2, 0.5), ("sat", 0.5, 0.8)]
    result = product.false_marks(machine, "the cat sat")
    assert result.marks == 1 and result.reference_words == 3


def test_two_labelled_windows_in_one_passage_are_both_kept(tmp_path: Path) -> None:
    grid = textgrid(2.0, "")

    def labelled(word: str) -> str:
        return grid.replace(
            'name = "words"\n        xmin = 0\n        xmax = 2.0\n        intervals: size = 1\n'
            "        intervals [1]:\n            xmin = 0\n            xmax = 2.0\n"
            '            text = ""',
            'name = "words"\n        xmin = 0\n        xmax = 2.0\n        intervals: size = 1\n'
            "        intervals [1]:\n            xmin = 0.5\n            xmax = 1.0\n"
            f'            text = "{word}"',
        )

    (tmp_path / "early.TextGrid").write_text(labelled("first"))
    (tmp_path / "late.TextGrid").write_text(labelled("second"))
    windows = tmp_path / "windows.json"
    windows.write_text(
        json.dumps(
            {
                "windows": {
                    "early": {"passage": "p1", "start_s": 10.0, "seconds": 2.0},
                    "late": {"passage": "p1", "start_s": 70.0, "seconds": 2.0},
                }
            }
        )
    )
    import_labels(windows, tmp_path)
    assert load_labels(tmp_path) == {"p1": [("first", 10.5, 11.0), ("second", 70.5, 71.0)]}
