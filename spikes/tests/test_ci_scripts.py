"""The speech-benchmarks workflow's scripts (exception E4): runner facts and the runner."""

import os
import subprocess
from pathlib import Path

CI = Path(__file__).resolve().parents[1] / "ci"


def test_runner_facts_record_every_fact_e4_requires(tmp_path: Path) -> None:
    out = tmp_path / "facts" / "runner-facts.txt"
    env = {
        **os.environ,
        "ImageOS": "ubuntu24",
        "ImageVersion": "20261026.1",
        "GITHUB_SHA": "abc123",
    }
    subprocess.run(["bash", str(CI / "runner-facts.sh"), str(out)], check=True, env=env)
    text = out.read_text()
    for heading in (
        "## lscpu",
        "## nproc",
        "## free -b",
        "## uname -m",
        "## runner image",
        "## commit",
    ):
        assert heading in text
    assert "ubuntu24 20261026.1" in text and "abc123" in text
    assert "CI-runner evidence (E4)" in text


def test_run_benchmark_refuses_an_unknown_benchmark_before_installing_anything() -> None:
    result = subprocess.run(
        ["bash", str(CI / "run-benchmark.sh")],
        env={**os.environ, "BENCHMARK": "b9", "RESULTS": "/nonexistent"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "unknown benchmark: b9" in result.stderr
