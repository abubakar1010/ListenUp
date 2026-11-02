"""Takedown fingerprints and the learner's removal notice (#105, NFR-USE-3, ADR 0098)."""

import pytest

from listenup.modules.content.domain import takedown

SHA = "ab" * 32


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        (f"upload:{SHA}", f"upload:{SHA}"),
        (f"upload:{SHA.upper()}", f"upload:{SHA}"),
        (f"  upload:{SHA}\n", f"upload:{SHA}"),
        (SHA, None),  # no source kind
        (f"upload:{SHA[:-1]}", None),
        (f"upload:{SHA}0", None),
        (f"upload:{SHA[:-1]}g", None),
        (f"upload:user:{SHA}", None),  # a learner's media fingerprint, not a source
        ("youtube:dQw4w9WgXcQ", None),  # #38
        ("", None),
    ],
)
def test_a_source_fingerprint_is_an_upload_hash_without_a_learner(
    given: str, stored: str | None
) -> None:
    assert takedown.source_fingerprint(given) == stored


@pytest.mark.parametrize(
    ("media", "sha"),
    [
        (f"upload:0190a9b2-0000-7000-8000-000000000001:{SHA}", SHA),
        (f"upload:0190a9b2-0000-7000-8000-000000000001:{SHA.upper()}", SHA),
        ("upload:0190a9b2-0000-7000-8000-000000000001:pending:0190", None),
        (f"youtube:{SHA}", None),
        (f"upload:{SHA}", None),
    ],
)
def test_the_hash_of_a_learners_upload_is_read_from_its_media_fingerprint(
    media: str, sha: str | None
) -> None:
    assert takedown.upload_hash(media) == sha


def test_an_upload_hash_becomes_its_takedown_fingerprint() -> None:
    assert takedown.upload_fingerprint(SHA.upper()) == f"upload:{SHA}"


@pytest.mark.parametrize(
    ("grounds", "why"),
    [
        ("copyright", "copyright owner asked us"),
        ("other_rights", "breaks someone else's rights"),
        ("unlawful", "the law does not allow us"),
    ],
)
def test_the_learner_reads_why_in_plain_words_and_that_their_practice_stays(
    grounds: str, why: str
) -> None:
    message = takedown.removal_message(grounds)
    assert message.startswith("We removed this clip because")
    assert why in message
    assert message.endswith("Your sessions, marks and cards are kept.")


def test_unknown_grounds_still_get_a_plain_reason() -> None:
    assert takedown.removal_message("new") == takedown.removal_message("other_rights")
