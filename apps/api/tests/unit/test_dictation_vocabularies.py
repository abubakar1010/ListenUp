"""The stored and API vocabularies of Dictation stay in step with the scoring domain (#54)."""

from decimal import Decimal
from typing import get_args

import pytest

from listenup.modules.dictation import repository
from listenup.modules.dictation.domain.scoring import WordStatus
from listenup.modules.dictation.schemas import DiffCounts
from listenup.modules.dictation.service import _result


def test_every_word_status_is_a_diff_status_and_a_count_except_not_scored():
    assert set(WordStatus) <= set(get_args(repository.DiffStatus))
    assert set(DiffCounts.model_fields) == {s.value for s in WordStatus if s != "not_scored"} | {
        "extra"
    }


def test_a_status_the_counts_do_not_know_fails_loudly_instead_of_vanishing():
    diff = {
        "words": [{"index": 0, "word": "a", "status": "invented", "typed": "a"}],
        "extras": [],
    }

    with pytest.raises(KeyError):
        _result(diff, Decimal(100))
