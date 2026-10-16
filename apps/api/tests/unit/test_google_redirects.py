"""OIDC return paths cannot become external destinations or server errors."""

import pytest

from listenup.modules.identity.oidc import safe_next


@pytest.mark.parametrize(
    "path", ["//evil.example", "https://evil.example", "http://[", "/\\evil.example", "/\r\n"]
)
def test_untrusted_redirects_fall_back_to_library(path: str) -> None:
    assert safe_next(path) == "/library"


def test_local_destination_is_preserved() -> None:
    assert safe_next("/settings?tab=account#delete") == "/settings?tab=account#delete"
