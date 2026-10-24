"""Who a failed sign-in is counted against (D17, UX-35, ADR 0057).

A real account is counted under its id, as before. An email with no live account is
counted too, under a keyed digest of the address, so a stranger cannot tell from the
answers whether an account exists. The digest keeps no readable part of the address.
"""

import hashlib
import hmac
import uuid

_DOMAIN = b"login-lock\x00"


def user_lock_subject(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


def email_lock_subject(key: bytes, email: str) -> str:
    """The subject for an address without a live account: case and spaces do not matter."""
    message = _DOMAIN + email.strip().casefold().encode()
    return "email:" + hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def attempts_left(failures: int, threshold: int) -> int:
    return max(0, threshold - failures)
