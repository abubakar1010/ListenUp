"""Timing and result-writing helpers shared by the spike scripts."""

import json
import os
import platform
import resource
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Timer:
    wall_s: float = 0.0
    cpu_s: float = 0.0  # this process (all threads) plus finished child processes


@contextmanager
def measure() -> Iterator[Timer]:
    """Measure wall time and CPU time (core-seconds), including ffmpeg child processes."""
    timer = Timer()
    w0 = time.perf_counter()
    c0 = time.process_time()
    ch0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        yield timer
    finally:
        ch1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        timer.wall_s = time.perf_counter() - w0
        timer.cpu_s = (time.process_time() - c0) + (
            (ch1.ru_utime + ch1.ru_stime) - (ch0.ru_utime + ch0.ru_stime)
        )


def machine_info() -> dict[str, Any]:
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_gb = None
    try:
        mem_kb = int(Path("/proc/meminfo").read_text().split()[1])
        mem_gb = round(mem_kb / 1024 / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return {
        "cpu": cpu,
        "cores": os.cpu_count(),
        "memory_gb": mem_gb,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "date": time.strftime("%Y-%m-%d"),
    }


@dataclass
class Report:
    """Collects rows and writes results/<name>.json and results/<name>.md."""

    name: str
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add(self, **row: Any) -> None:
        self.rows.append(row)
        print("  " + "  ".join(f"{k}={row.get(k)}" for k in self.columns), flush=True)

    def write(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        info = machine_info()
        data = {"machine": info, "summary": self.summary, "rows": self.rows}
        (out_dir / f"{self.name}.json").write_text(json.dumps(data, indent=2, default=str))
        lines = [f"# {self.name}", "", f"Machine: {info}", ""]
        lines += [f"- **{k}**: {v}" for k, v in self.summary.items()] + [""]
        lines.append("| " + " | ".join(self.columns) + " |")
        lines.append("|" + " --- |" * len(self.columns))
        for row in self.rows:
            lines.append("| " + " | ".join(_fmt(row.get(c)) for c in self.columns) + " |")
        path = out_dir / f"{self.name}.md"
        path.write_text("\n".join(lines) + "\n")
        return path


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return "" if value is None else str(value)
