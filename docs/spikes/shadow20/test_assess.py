"""Orchestration regressions: boundary fakes prove score eligibility, not model quality."""

from copy import deepcopy

import experiment
import numpy as np
import pytest


def assess(
    monkeypatch, transcript, *, phone_mean=-1.0, bad_alignment=False, text="we go home"
):
    aligned = [
        {"word": w, "start": i * 0.4, "end": i * 0.4 + 0.2}
        for i, w in enumerate(text.split())
    ]
    phones = [
        {"phones": ["a"], "gop": [-1.0], "mean": -1.0, "ending": -1.0} for _ in aligned
    ]
    candidate = deepcopy(phones)
    for p in candidate:
        p.update(gop=[phone_mean], mean=phone_mean, ending=phone_mean)
    candidate_alignment = deepcopy(aligned)
    if bad_alignment:
        candidate_alignment[1]["end"] = candidate_alignment[1]["start"]

    class Models:
        def word_align(self, audio, text):
            return candidate_alignment

        def phone_profile(self, audio, text):
            return candidate

        def recognize(self, audio):
            return transcript

    monkeypatch.setattr(experiment, "pitch", lambda audio, words: [None] * len(words))
    ref = {
        "aligned": aligned,
        "phones": phones,
        "pitch": [None] * len(aligned),
        "transcript": text,
    }
    audio = np.ones(16000)
    return experiment.assess(Models(), audio, audio, text, ref)


@pytest.mark.parametrize("transcript", ["", "we home"])
def test_incomplete_word_evidence_cannot_grade_forced_phones(monkeypatch, transcript):
    result = assess(monkeypatch, transcript)
    assert result["scores"]["pronunciation"] is None
    assert result["scores"]["articulation"] is None
    assert result["gop_evidence"]["reason"] == "incomplete_word_evidence"
    assert result["phones"][1]["gop"] == [-1.0]  # retain diagnostic evidence
    assert result["markers"][1] == "unknown"
    assert "missed" not in result["markers"]  # ASR absence is not an omission label


def test_complete_word_evidence_allows_reference_relative_gop(monkeypatch):
    result = assess(monkeypatch, "we go home")
    assert result["scores"]["pronunciation"] == 100
    assert result["scores"]["articulation"] == 100
    assert result["gop_evidence"]["reason"] is None
    assert result["markers"] == ["good"] * 3
    worse = assess(monkeypatch, "we go home", phone_mean=-2.0)
    assert 0 < worse["scores"]["pronunciation"] < 100
    assert worse["markers"] == ["needs work"] * 3


@pytest.mark.parametrize("phone_mean", [float("nan"), float("inf")])
def test_nonfinite_phone_evidence_cannot_become_perfect_gop(monkeypatch, phone_mean):
    result = assess(monkeypatch, "we go home", phone_mean=phone_mean)
    assert result["scores"]["pronunciation"] is None
    assert result["scores"]["articulation"] is None
    assert result["gop_evidence"]["reason"] == "invalid_phone_evidence"
    assert result["markers"] == ["unknown"] * 3


def test_invalid_alignment_cannot_grade_gop(monkeypatch):
    result = assess(monkeypatch, "we go home", bad_alignment=True)
    assert result["scores"]["pronunciation"] is None
    assert result["scores"]["articulation"] is None
    assert result["gop_evidence"]["reason"] == "invalid_alignment"


@pytest.mark.parametrize(
    "text, transcript",
    [
        ("we go home", "we go go home"),
        ("we go go home", "we go home"),
    ],
)
def test_repeated_word_occurrence_is_unknown_when_counts_disagree(
    monkeypatch, text, transcript
):
    result = assess(monkeypatch, transcript, text=text)
    assert result["scores"]["pronunciation"] is None
    assert result["scores"]["articulation"] is None
    assert result["gop_evidence"]["reason"] == "ambiguous_word_evidence"
    for i, word in enumerate(text.split()):
        if word == "go":
            assert result["markers"][i] == "unknown"
            assert result["word_evidence"][i] == "unknown"
