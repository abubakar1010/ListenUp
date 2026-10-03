import pytest

from listenup.modules.identity.domain.credentials import (
    email_problem,
    normalize_email,
    password_problem,
)


@pytest.mark.parametrize("email", ["a@b.co", "first.last+tag@mail.example.org"])
def test_valid_emails(email: str) -> None:
    assert email_problem(email) is None


@pytest.mark.parametrize(
    "email", ["", "plain", "a@b", "a b@c.de", "a@b.", "@b.co", "a@" + "b" * 260 + ".co"]
)
def test_invalid_emails(email: str) -> None:
    assert email_problem(email)


def test_emails_are_trimmed_but_keep_their_case() -> None:
    assert normalize_email("  Name@Example.com ") == "Name@Example.com"


@pytest.mark.parametrize(
    ("password", "ok"),
    [("1234567", False), ("12345678", True), ("x" * 128, True), ("x" * 129, False)],
)
def test_password_length(password: str, ok: bool) -> None:
    assert (password_problem(password) is None) is ok
