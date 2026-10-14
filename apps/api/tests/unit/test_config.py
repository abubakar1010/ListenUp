"""Configuration refuses a shared development analytics key in production."""

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
