"""Configuration refuses development-only values in production: the shared analytics
key and placeholder consent versions."""

import pytest
from pydantic import SecretStr, ValidationError

from listenup.platform.config import Settings


def test_production_requires_a_dedicated_analytics_hmac_key() -> None:
    with pytest.raises(ValidationError, match="LISTENUP_ANALYTICS_HMAC_KEY"):
        Settings(environment="production")


def test_production_accepts_a_dedicated_analytics_hmac_key() -> None:
    settings = Settings(
        environment="production",
        analytics_hmac_key=SecretStr("a-stable-production-analytics-key-123"),
    )

    assert settings.analytics_hmac_key.get_secret_value().endswith("-123")


def test_production_rejects_a_short_analytics_hmac_key() -> None:
    with pytest.raises(ValidationError, match="at least 32 items"):
        Settings(
            environment="production",
            analytics_hmac_key=SecretStr("too-short"),
        )


PRODUCTION_KEY = SecretStr("a-stable-production-analytics-key-123")


@pytest.mark.parametrize("field", ["terms_version", "privacy_version", "voice_consent_version"])
def test_production_refuses_a_placeholder_consent_version(field: str) -> None:
    # ADR 0048 left this to #103: a placeholder label has no published text.
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(
            environment="production",
            analytics_hmac_key=PRODUCTION_KEY,
            **{field: "placeholder-1"},
        )


def test_local_runs_accept_a_placeholder_consent_version() -> None:
    settings = Settings(environment="local", terms_version="placeholder-1")

    assert settings.terms_version == "placeholder-1"
