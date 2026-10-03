"""Dictation scoring: classes, accuracy and mark candidates (FR-DI-5, FR-DI-6, issue #53)."""

import json
import random
import time
from decimal import Decimal

import pytest

from listenup.modules.dictation.domain import (
    SPELLING_SLIPS_COUNT_AS_CORRECT,
    DictationScore,
    ExtraWord,
    MarkCandidate,
    ReferenceWord,
    WordStatus,
    reference_from_arrays,
    score_dictation,
    scoring,
)

RIGHT_QUOTE = chr(0x2019)
EM_DASH = chr(0x2014)
VOCABULARY = (
    "the of and to in is you that it he was for on are as with his they at be this "
    "have from or one had by word but not what all were we when your can said there "
    "use an each which she do how their if will up other about out many then them "
    "these so some her would make like him into time has look two more write go see "
    "number no way could've people my than first water been call who oil its now "
    "find long down day did get come made may part colour 1990 twenty-five isn't"
)

C, S, W, M, N = (
    WordStatus.CORRECT,
    WordStatus.SPELLING_SLIP,
    WordStatus.WRONG,
    WordStatus.MISSING,
    WordStatus.NOT_SCORED,
)


def reference(text: str) -> tuple[ReferenceWord, ...]:
    """One word every 400 ms, each 300 ms long."""
    return tuple(ReferenceWord(w, i * 400, i * 400 + 300) for i, w in enumerate(text.split()))


def score(ref: str, typed: str) -> DictationScore:
    return score_dictation(reference(ref), typed)


def statuses(result: DictationScore) -> list[WordStatus]:
    return [word.status for word in result.words]


# Accuracy counts correct words, and spelling slips while SPELLING_SLIPS_COUNT_AS_CORRECT.
@pytest.mark.parametrize(
    ("ref", "typed", "expected", "extras", "accuracy"),
    [
        ("The cat sat on the mat.", "the cat sat on the mat", [C, C, C, C, C, C], [], "100.00"),
        ("The cat sat on the mat.", "", [M, M, M, M, M, M], [], "0.00"),
        ("The cat sat on the mat.", "the cat sat the mat", [C, C, C, M, C, C], [], "83.33"),
        ("The cat sat on the mat.", "the cat sat in the mat", [C, C, C, W, C, C], [], "83.33"),
        (
            "The cat sat on the mat.",
            "the fat cat sat on the mat",
            [C, C, C, C, C, C],
            ["fat"],
            "100.00",
        ),
        ("The brown fox jumps.", "the brwn fox jump", [C, S, C, S], [], "100.00"),
        ("I could've told you.", "I could have told you", [C, C, C, C], [], "100.00"),
        ("I could have told you.", "I could've told you", [C, C, C, C, C], [], "100.00"),
        ("I could've told you.", "I could told you", [C, W, C, C], [], "75.00"),
        ("It was fifteen", "it was 15", [C, C, C], [], "100.00"),
        ("Born in 1990", "born in nineteen ninety", [C, C, C], [], "100.00"),
        ("The colour grey", "the color gray", [C, C, C], [], "100.00"),
        ("He's here", "he is here", [C, C], [], "100.00"),
        ("He'd go", "he had go", [C, C], [], "100.00"),
        (f"Don{RIGHT_QUOTE}t STOP!", "dont stop", [S, C], [], "100.00"),
        ("a lot of fun", "alot of fun", [S, S, C, C], [], "100.00"),
        (f"Hello {EM_DASH} there", "hello there", [C, N, C], [], "100.00"),
        ("we went there", "we went their", [C, C, S], [], "100.00"),
        ("we went in", "we went on", [C, C, W], [], "66.67"),
        ("the the the", "the the", [C, C, M], [], "66.67"),
    ],
)
def test_known_pairs(
    ref: str, typed: str, expected: list[WordStatus], extras: list[str], accuracy: str
) -> None:
    result = score(ref, typed)
    assert statuses(result) == expected
    assert [extra.typed for extra in result.extras] == extras
    assert result.accuracy == Decimal(accuracy)


def test_slips_count_as_correct_and_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert SPELLING_SLIPS_COUNT_AS_CORRECT is True
    result = score("the brown fox", "the brwn fox")
    assert (result.correct_count, result.slip_count, result.accuracy) == (2, 1, Decimal("100.00"))
    monkeypatch.setattr(scoring, "SPELLING_SLIPS_COUNT_AS_CORRECT", False)
    assert score("the brown fox", "the brwn fox").accuracy == Decimal("66.67")


def test_typed_text_is_reported_per_reference_word() -> None:
    result = score("I could've seen 1990 there", "I could have seen nineteen ninety thier")
    assert [(w.word, w.typed) for w in result.words] == [
        ("I", "I"),
        ("could've", "could have"),
        ("seen", "seen"),
        ("1990", "nineteen ninety"),
        ("there", "thier"),
    ]
    assert result.words[4].status is S


def test_number_words_in_the_reference_share_one_verdict() -> None:
    result = score("in nineteen ninety we left", "in 1990 we left")
    assert statuses(result) == [C, C, C, C, C]
    assert [w.typed for w in result.words[1:3]] == ["1990", "1990"]

    wrong = score("in nineteen ninety we left", "in 1991 we left")
    assert statuses(wrong) == [C, W, W, C, C]
    assert [m.word_index for m in wrong.mark_candidates] == [1, 2]


def test_mark_candidates_carry_word_index_and_audio_time() -> None:
    ref = (
        ReferenceWord("We", 1000, 1200),
        ReferenceWord("could've", 1200, 1650),
        ReferenceWord("gone", 1650, 1900),
        ReferenceWord("home.", 1900, 2400),
    )
    result = score_dictation(ref, "we could gone hum hum", first_word_index=40)
    assert result.mark_candidates == (
        MarkCandidate(41, "could've", W, 1200, 1650),
        MarkCandidate(43, "home.", W, 1900, 2400),
    )
    assert [w.index for w in result.words] == [40, 41, 42, 43]
    # Two equal-cost alignments; the tie-break pairs "home." with the last "hum".
    assert result.extras == (ExtraWord("hum", 43),)


def test_spelling_slips_and_correct_words_are_not_mark_candidates() -> None:
    assert score("the brown fox", "the brwn fox").mark_candidates == ()


def test_extras_record_where_they_were_typed() -> None:
    result = score("one two three", "um one two er three yes")
    assert result.extras == (ExtraWord("um", 0), ExtraWord("er", 2), ExtraWord("yes", 3))
    assert result.extra_count == 3


def test_extra_part_of_a_typed_word_is_reported() -> None:
    result = score("I could go", "I could've go")
    assert statuses(result) == [C, C, C]
    assert result.extras == (ExtraWord("have", 2),)


def test_everything_extra_against_punctuation_only_reference() -> None:
    result = score(f"{EM_DASH} ...", "hello there")
    assert statuses(result) == [N, N]
    assert result.scored_count == 0
    assert result.accuracy == Decimal("0.00")
    assert [e.typed for e in result.extras] == ["hello", "there"]


def test_empty_reference() -> None:
    result = score_dictation((), "anything")
    assert result.words == ()
    assert result.accuracy == Decimal("0.00")


def test_case_and_punctuation_do_not_matter() -> None:
    plain = score("Well, I think so.", "well i think so")
    noisy = score("Well, I think so.", '"WELL"... I -- think; so?!')
    assert statuses(plain) == statuses(noisy) == [C, C, C, C]


def test_counts_add_up() -> None:
    result = score("one two three four five six", "one too four fiv six seven")
    assert result.correct_count + result.slip_count + result.wrong_count + result.missing_count == 6
    assert result.scored_count == 6


def test_diff_json_round_trips_through_json() -> None:
    result = score("Hello there friend", "hello chair um friend")
    document = json.loads(json.dumps(result.diff_json()))
    assert document == {
        "version": 1,
        "slips_count_as_correct": True,
        "words": [
            {"index": 0, "word": "Hello", "status": "correct", "typed": "hello"},
            {"index": 1, "word": "there", "status": "wrong", "typed": "chair"},
            {"index": 2, "word": "friend", "status": "correct", "typed": "friend"},
        ],
        "extras": [{"typed": "um", "before_index": 2}],
    }
    assert json.loads(json.dumps(result.mark_candidates[0].to_json())) == {
        "word_index": 1,
        "word": "there",
        "status": "wrong",
        "at_ms": 400,
        "end_ms": 700,
    }


def test_reference_from_transcript_arrays() -> None:
    ref = reference_from_arrays(["Hi", "there"], [0, 300], [250, 600])
    assert ref == (ReferenceWord("Hi", 0, 250), ReferenceWord("there", 300, 600))
    with pytest.raises(ValueError, match="differ in length"):
        reference_from_arrays(["Hi"], [0, 1], [2])
    with pytest.raises(ValueError, match="invalid word time"):
        ReferenceWord("Hi", 500, 100)


def test_long_passage_scores_within_budget() -> None:
    """A 15-minute passage (FR-DI-1) of about 2,500 words with typical errors."""
    rng = random.Random(53)
    vocabulary = VOCABULARY.split()
    ref_words = [rng.choice(vocabulary) for _ in range(2500)]
    typed: list[str] = []
    for w in ref_words:
        roll = rng.random()
        if roll < 0.03:
            continue
        if roll < 0.06:
            typed.append(rng.choice(vocabulary))
        elif roll < 0.08:
            typed.extend([w, rng.choice(vocabulary)])
        elif roll < 0.10 and len(w) > 4:
            typed.append(w[:-1])
        else:
            typed.append(w)
    ref = tuple(ReferenceWord(w, i * 360, i * 360 + 300) for i, w in enumerate(ref_words))
    text = " ".join(typed)

    best = min(_timed(ref, text) for _ in range(3))
    assert best < 0.2
    result = score_dictation(ref, text)
    assert len(result.words) == 2500
    assert Decimal(85) < result.accuracy < Decimal(100)


def _timed(ref: tuple[ReferenceWord, ...], text: str) -> float:
    started = time.perf_counter()
    score_dictation(ref, text)
    return time.perf_counter() - started
