"""The Card step's suggestion order (#74, FR-CA-4, PRD CA-5)."""

import uuid

from listenup.modules.cards.domain.suggestions import Candidate, rank


def candidate(phrase: str, tag: str | None = None) -> Candidate:
    return Candidate(mark_id=uuid.uuid4(), phrase=phrase, tag=tag)


def order(candidates: list[Candidate], earlier: frozenset[str] = frozenset()) -> list[str]:
    return [candidate_of(candidates, s.mark_id).phrase for s in rank(candidates, earlier)]


def candidate_of(candidates: list[Candidate], mark_id: uuid.UUID) -> Candidate:
    return next(c for c in candidates if c.mark_id == mark_id)


def test_tagged_reduction_a_lot_of_is_suggested():
    marks = [candidate("cat"), candidate("a lot of", "reduction")]
    ranked = rank(marks, frozenset())
    assert ranked[0].mark_id == marks[1].mark_id
    assert ranked[0].suggested
    assert ranked[0].reasons == ("multi_word", "reduction")


def test_each_reason_alone_makes_a_suggestion():
    assert rank([candidate("kind of")], frozenset())[0].reasons == ("multi_word",)
    assert rank([candidate("gonna", "weak_form")], frozenset())[0].reasons == ("weak_form",)
    assert rank([candidate("gonna", "linking")], frozenset())[0].reasons == ("linking",)
    assert rank([candidate("gonna")], frozenset({"gonna"}))[0].reasons == ("earlier_session",)


def test_plain_single_word_and_unknown_word_are_not_suggested():
    ranked = rank([candidate("cat"), candidate("zyzzyva", "unknown_word")], frozenset())
    assert [s.suggested for s in ranked] == [False, False]
    assert all(s.reasons == () for s in ranked)


def test_suggested_come_first_and_each_group_keeps_audio_order():
    marks = [
        candidate("one"),
        candidate("two words"),
        candidate("three"),
        candidate("four", "linking"),
    ]
    assert order(marks) == ["two words", "four", "one", "three"]


def test_earlier_phrase_match_ignores_case_punctuation_and_spacing():
    marks = [candidate("cat"), candidate("  Gonna, ")]
    assert order(marks, frozenset({"gonna"})) == ["  Gonna, ", "cat"]


def test_blank_phrase_is_not_a_multi_word_suggestion():
    assert rank([candidate("   ")], frozenset())[0].suggested is False


def test_empty_input_gives_empty_order():
    assert rank([], frozenset()) == []


def test_earlier_phrase_match_treats_a_curly_apostrophe_as_straight():
    # Same folding as analytics.domain.events.mark_pattern: phone keyboards type a curly one.
    marks = [candidate("cat"), candidate("don\u2019t")]
    assert order(marks, frozenset({"don't"})) == ["don\u2019t", "cat"]
