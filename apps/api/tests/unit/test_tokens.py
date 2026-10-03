"""Secret tokens for cookies and emailed links (NFR-SEC-1, FR-ACC-3)."""

import hashlib

from listenup.modules.identity.domain.tokens import new_token, reset_link, token_hash


def test_tokens_are_long_random_and_url_safe() -> None:
    tokens = {new_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(
        len(token) >= 43 and token.replace("-", "").replace("_", "").isalnum() for token in tokens
    )


def test_only_the_sha256_is_kept() -> None:
    assert token_hash("abc") == hashlib.sha256(b"abc").digest()


def test_the_token_travels_in_the_fragment() -> None:
    assert (
        reset_link("https://app.example/", "tok") == "https://app.example/reset-password#token=tok"
    )
