"""Who is an administrator (#100, SRS 2.2, ADR 0034)."""

from collections.abc import Iterable


def is_admin(email: str, verified: bool, admin_emails: Iterable[str]) -> bool:
    """An account is an admin when its email is listed and the address is verified.

    Emails compare without case or surrounding spaces, as the database compares them.
    The verified address matters: an account can be registered with any email, so an
    unverified one could claim a listed address nobody had signed up with yet.
    """
    if not verified:
        return False
    wanted = email.strip().casefold()
    return any(wanted == listed.strip().casefold() for listed in admin_emails if listed.strip())
