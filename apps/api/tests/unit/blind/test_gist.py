"""Counting the sentences of a gist (#65; final UI D04)."""

import pytest

from listenup.modules.blind.domain import count_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("The speaker talks about trees", 0),  # not finished yet
        ("The speaker talks about trees.", 1),
        ("Trees cool streets. Shade lowers heat! Do roots break pipes?", 3),
        ("Trees cool streets.Shade lowers heat.", 0 + 1),  # no space after the first stop
        ("Yes. No. Trees cool streets.", 1),  # under three words each
        ("It's well-known that trees help. They cost money... Cities plant them anyway!", 3),
        ("The tree is 3.5 metres tall. It grows fast in rain.", 2),
        ("Mr. Smith plants trees. He likes oaks a lot.", 2),
        ("Trees cool streets.\nShade lowers heat.\n\nRoots need space.", 3),
        ("Trees cool streets. Shade lowers heat. Roots need", 2),
        ("... . ! ?", 0),
    ],
)
def test_sentences_end_with_punctuation_and_have_three_words(text: str, expected: int) -> None:
    assert count_sentences(text) == expected
