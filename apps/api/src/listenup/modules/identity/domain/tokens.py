"""Secret tokens in cookies and emailed links (NFR-SEC-1).

A token is 32 random bytes in URL-safe text. Only its SHA-256 is stored, so a copy
of the database cannot be used to sign in or reset a password.
"""

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def reset_link(web_base_url: str, token: str) -> str:
    """The page that sets a new password. The token sits in the fragment, which the
    browser never sends to a server, so it stays out of access logs and Referer headers.
    """
    return f"{web_base_url.rstrip('/')}/reset-password#token={token}"
