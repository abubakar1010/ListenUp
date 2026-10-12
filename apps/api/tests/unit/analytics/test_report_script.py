"""Regression tests for analytics report CLI validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_report_script():
    script_path = Path(__file__).parents[3] / "scripts" / "analytics_report.py"
    spec = importlib.util.spec_from_file_location("analytics_report", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_cli_rejects_an_incomplete_range(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _load_report_script()
    monkeypatch.setattr(
        "sys.argv",
        [
            "analytics_report.py",
            "--from",
            "2026-10-01",
            "--to",
            "2026-10-31",
            "--as-of",
            "2026-10-12T00:00:00+00:00",
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        report.main()

    assert "--as-of must be at or after the end of the --to UTC day" in capsys.readouterr().err
