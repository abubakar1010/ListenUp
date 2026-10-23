"""The report connection belongs only to the API container (#100, ADR 0051)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]


def test_compose_passes_report_connection_only_to_api() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose required to resolve environment overrides")
    report_url = "postgresql://report@example.invalid/listenup"
    config = json.loads(
        subprocess.check_output(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            env={**os.environ, "LISTENUP_ADMIN_REPORT_DATABASE_URL": report_url},
        )
    )
    assert (
        config["services"]["api"]["environment"].get("LISTENUP_ADMIN_REPORT_DATABASE_URL")
        == report_url
    )
    for name in ("worker", "worker-media", "migrate"):
        assert "LISTENUP_ADMIN_REPORT_DATABASE_URL" not in config["services"][name]["environment"]
