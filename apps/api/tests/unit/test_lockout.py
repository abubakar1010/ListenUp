"""Who a failed sign-in is counted against (D17, UX-35, ADR 0057)."""

import uuid

from listenup.modules.identity.domain.lockout import (
    attempts_left,
    email_lock_subject,
    user_lock_subject,
)

KEY = b"k" * 32


def test_an_email_is_counted_under_a_keyed_digest_that_hides_the_address() -> None:
    subject = email_lock_subject(KEY, "Learner@Example.com")

    assert subject.startswith("email:")
    assert len(subject) == len("email:") + 32
    assert "learner" not in subject.lower()


def test_the_same_address_in_any_case_or_with_spaces_counts_once() -> None:
    assert email_lock_subject(KEY, " learner@example.com ") == email_lock_subject(
        KEY, "LEARNER@EXAMPLE.COM"
    )


def test_another_key_or_address_gives_another_subject() -> None:
    base = email_lock_subject(KEY, "a@example.com")

    assert email_lock_subject(b"x" * 32, "a@example.com") != base
    assert email_lock_subject(KEY, "b@example.com") != base


def test_an_account_is_counted_under_its_id() -> None:
    user = uuid.UUID("01a16859-3414-7522-8bf8-0d250b26c914")

    assert user_lock_subject(user) == f"user:{user}"


def test_tries_left_count_down_to_zero_and_never_below() -> None:
    assert [attempts_left(failures, 5) for failures in range(7)] == [5, 4, 3, 2, 1, 0, 0]
