"""Rules for the email and password a learner signs up with (FR-ACC-1)."""

import re

MAX_EMAIL = 254
MIN_PASSWORD = 8
MAX_PASSWORD = 128

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


def normalize_email(email: str) -> str:
    """Trim spaces; case is kept for display, and the database compares without case."""
    return email.strip()


def email_problem(email: str) -> str | None:
    if len(email) > MAX_EMAIL or not _EMAIL.match(email):
        return "Enter an email address like name@example.com."
    return None


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters for your password."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters for your password."
    return None
