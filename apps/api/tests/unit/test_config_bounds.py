"""Settings that would crash a service on start are refused when they are read."""

import pytest
from pydantic import ValidationError

from listenup.platform.config import Settings


@pytest.mark.parametrize(
    "values",
    [
        {"backup_hour_utc": 24},
        {"backup_hour_utc": -1},
        {"backup_minute_utc": 60},
        {"backup_retention_days": 0},
        {"otel_trace_sample_ratio": 1.5},
        {"otel_trace_sample_ratio": -0.1},
        {"otel_metrics_interval_seconds": 0},
    ],
)
def test_out_of_range_values_are_refused(values: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_the_defaults_are_in_range() -> None:
    settings = Settings()
    assert (settings.backup_hour_utc, settings.backup_minute_utc) == (2, 30)
