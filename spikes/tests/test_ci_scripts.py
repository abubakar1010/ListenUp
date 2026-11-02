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


def check_results(folder: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CI / "check-results.sh"), str(folder)], capture_output=True, text=True
    )


def test_check_results_allows_only_numbers_and_text(tmp_path: Path) -> None:
    for name in (
        "spike-22-b4-fillers.json",
        "spike-22-b4-fillers.md",
        "runner-facts.txt",
        "rows.csv",
    ):
        (tmp_path / name).write_text("x")
    assert check_results(tmp_path).returncode == 0
    for name in ("clip.opus", "nested/clip.raw", "windows.zip"):
        bad = tmp_path / name
        bad.parent.mkdir(exist_ok=True)
        bad.write_bytes(b"x")
        result = check_results(tmp_path)
        assert result.returncode == 1 and name in result.stdout
        bad.unlink()


def test_container_facts_record_the_cpu_memory_and_swap_limits(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "cpu.max").write_text("200000 100000\n")
    (cgroup / "memory.max").write_text("12884901888\n")
    (cgroup / "memory.swap.max").write_text("0\n")
    out = tmp_path / "container-facts.txt"
    subprocess.run(
        ["bash", str(CI / "container-facts.sh"), str(out)],
        check=True,
        env={**os.environ, "CGROUP_ROOT": str(cgroup), "OMP_NUM_THREADS": "2"},
    )
    text = out.read_text()
    for expected in ("200000 100000", "12884901888", "## memory.swap.max\n0", "OMP_NUM_THREADS=2"):
        assert expected in text
