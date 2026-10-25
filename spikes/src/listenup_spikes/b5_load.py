"""B5 (#94): load-test the API and Blind heartbeats, and report against System Design 1.1.

Starts the stack (infra/compose/compose.yml with spikes/load/compose.b5.yml), seeds N
learners with apps/api/scripts/seed_load.py, runs spikes/load/b5.js in the pinned k6
image, samples `docker stats` for CPU and dumps the heaviest pg_stat_statements entries.

    spike-b5 --out results/b5-local                # local: labelled as not stage-0
    spike-b5 --stage0 --out results/b5-stage0      # only on the stage-0 server (#16)

Percentiles are nearest-rank over every request of the measured window, failed
requests included. CPU is each container's share of all host cores. Writes
results.json, results.md and requests.csv.gz (one line per request) in --out.
"""

import argparse
import csv
import gzip
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Any

from listenup_spikes.common import machine_info

# System Design 1.1 and 12.1 (B5): p95 under 200 ms (reads) and 300 ms (writes) at under
# 30% CPU. "Under" is strict: exactly 200 ms misses.
READ_P95_MS = 200.0
WRITE_P95_MS = 300.0
CPU_LIMIT_PCT = 30.0
# A statement this slow on average is listed for a fix or a follow-up story (#94).
SLOW_MEAN_MS = 10.0

LOCAL_LABEL = "Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)"
STAGE0_LABEL = "Stage-0 server run (#16): qualifies for #155 after independent review"

K6_IMAGE = "grafana/k6:1.3.0"
K6_CONTAINER = "listenup-b5-k6"
SERVICES = ("postgres", "storage", "storage-bucket", "migrate", "api", "worker")
GROUPS = ("read", "write", "heartbeat", "all")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_OWN_QUERIES = ("pg_stat_statements", "CREATE EXTENSION")


@dataclass(frozen=True)
class Request:
    """One HTTP request as k6 timed it. `status` 0 means no response (timeout, refused)."""

    phase: str  # warmup or measure
    kind: str  # read, write or heartbeat
    name: str  # method and route template
    status: int
    duration_ms: float
    error: str = ""  # k6's error_code when there was no response


def _label(r: Request) -> str:
    return f"{r.name} {r.status}" + (f" (k6 error {r.error})" if r.error else "")


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least q of the values at or
    below it. None when there are no values."""
    if not 0 < q <= 1:
        raise ValueError("q must be in (0, 1]")
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(q * len(ordered)) - 1]


def parse_k6_points(lines: Iterable[str]) -> tuple[list[Request], dict[str, int]]:
    """Request durations, and the measured window's Blind stops by reason, from
    `k6 run --out json` lines."""
    requests: list[Request] = []
    stops: Counter[str] = Counter()
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") != "Point":
            continue
        data = item["data"]
        tags = data.get("tags") or {}
        if item["metric"] == "http_req_duration":
            requests.append(
                Request(
                    phase=tags.get("phase", ""),
                    kind=tags.get("kind", ""),
                    name=tags.get("name", ""),
                    status=int(tags.get("status") or 0),
                    duration_ms=float(data["value"]),
                    error=tags.get("error_code", ""),
                )
            )
        elif item["metric"] == "blind_stops" and tags.get("phase") == "measure":
            stops[tags.get("reason", "")] += int(data["value"])
    return requests, dict(stops)


def _is_error(status: int) -> bool:
    return status == 0 or status >= 400


def _group(requests: list[Request]) -> dict[str, Any]:
    durations = [r.duration_ms for r in requests]
    errors = sum(1 for r in requests if _is_error(r.status))
    return {
        "count": len(requests),
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "max_ms": max(durations) if durations else None,
        "errors": errors,
        "error_rate": errors / len(requests) if requests else 0.0,
        "by_status": dict(Counter(str(r.status) for r in requests)),
    }


def summarise_requests(requests: Iterable[Request]) -> dict[str, Any]:
    """Latency and errors of the measured window per group. Heartbeats are writes for
    the 300 ms target and are also shown on their own."""
    measured = [r for r in requests if r.phase == "measure"]
    members = {
        "read": [r for r in measured if r.kind == "read"],
        "write": [r for r in measured if r.kind in ("write", "heartbeat")],
        "heartbeat": [r for r in measured if r.kind == "heartbeat"],
        "all": measured,
    }
    summary: dict[str, Any] = {group: _group(members[group]) for group in GROUPS}
    summary["errors_by_endpoint"] = dict(
        Counter(_label(r) for r in measured if _is_error(r.status))
    )
    summary["by_endpoint"] = {
        name: _group([r for r in measured if r.name == name])
        for name in sorted({r.name for r in measured})
    }
    return summary


def achieved_rates(summary: dict[str, Any], duration_s: float) -> dict[str, float | None]:
    """Requests per second actually sent in the measured window: everything but
    heartbeats (Blind attempt starts included), and heartbeats."""
    if duration_s <= 0:
        return {"mixed_rps": None, "heartbeat_rps": None}
    beats = summary["heartbeat"]["count"]
    return {
        "mixed_rps": (summary["all"]["count"] - beats) / duration_s,
        "heartbeat_rps": beats / duration_s,
    }


def parse_stats_line(line: str) -> tuple[str, float] | None:
    """(container name, percent of one core) from a `docker stats --format json` line."""
    text = _ANSI.sub("", line).strip()
    if not text.startswith("{"):
        return None
    item = json.loads(text)
    try:
        return item["Name"], float(item["CPUPerc"].rstrip("%"))
    except (KeyError, ValueError):
        return None


def _cpu(values: list[float], cores: int) -> dict[str, Any]:
    shares = [v / cores for v in values]
    return {
        "mean_pct": sum(shares) / len(shares) if shares else None,
        "p95_pct": percentile(shares, 0.95),
        "max_pct": max(shares) if shares else None,
        "samples": len(shares),
    }


def summarise_cpu(
    samples: Iterable[tuple[str, float]], cores: int, roles: dict[str, str]
) -> dict[str, Any]:
    """CPU per role as a share of all host cores. `server` is the API, database and
    worker summed per sampling round (each round has one sample per container); the
    load generator (`load`) is reported but is not part of the server."""
    per_role: dict[str, list[float]] = {role: [] for role in roles.values()}
    rounds: list[float] = []
    seen: set[str] = set()
    current = 0.0
    for name, pct in samples:
        role = roles.get(name)
        if role is None:
            continue
        if name in seen:  # a container repeats: the previous round is complete
            rounds.append(current)
            seen, current = set(), 0.0
        seen.add(name)
        per_role[role].append(pct)
        if role != "load":
            current += pct
    if seen:
        rounds.append(current)
    result = {role: _cpu(values, cores) for role, values in per_role.items()}
    result["server"] = _cpu(rounds, cores)
    return result


def rank_statements(
    rows: Iterable[dict[str, Any]], top: int, slow_mean_ms: float = SLOW_MEAN_MS
) -> dict[str, list[dict[str, Any]]]:
    """The heaviest statements by total and by mean time, and every statement whose mean
    is at or over `slow_mean_ms`. The runner's own statements are left out."""
    kept = [r for r in rows if not any(own in r["query"] for own in _OWN_QUERIES)]
    return {
        "by_total": sorted(kept, key=lambda r: r["total_ms"], reverse=True)[:top],
        "by_mean": sorted(kept, key=lambda r: r["mean_ms"], reverse=True)[:top],
        "slow": sorted(
            (r for r in kept if r["mean_ms"] >= slow_mean_ms),
            key=lambda r: r["mean_ms"],
            reverse=True,
        ),
    }


def verdict(summary: dict[str, Any], cpu: dict[str, Any], *, stage0: bool) -> dict[str, Any]:
    """Against System Design 1.1 and 12.1. A missing measurement fails its check."""

    def under(value: float | None, limit: float) -> bool:
        return value is not None and value < limit

    checks = {
        "read_p95": under(summary["read"]["p95_ms"], READ_P95_MS),
        "write_p95": under(summary["write"]["p95_ms"], WRITE_P95_MS),
        "cpu": under(cpu["server"]["mean_pct"], CPU_LIMIT_PCT),
    }
    return {
        "checks": checks,
        "meets_targets": all(checks.values()),
        "stage0_evidence": stage0,
        "label": STAGE0_LABEL if stage0 else LOCAL_LABEL,
        "targets": {
            "read_p95_ms": READ_P95_MS,
            "write_p95_ms": WRITE_P95_MS,
            "server_cpu_mean_pct": CPU_LIMIT_PCT,
        },
    }


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    env, load, verdict_ = report["environment"], report["load"], report["verdict"]
    where = "stage-0" if verdict_["stage0_evidence"] else "local Docker Compose, not stage-0"
    lines = [
        f"# B5 load test ({where})",
        "",
        f"**{verdict_['label']}**",
        "",
        f"- Host: {env.get('host')}; {env.get('cores')} cores; commit {env.get('git_sha')}",
        f"- Load: {load['mixed_rps']} req/s mixed plus {load['blind_learners']} Blind learners "
        f"(one heartbeat per 5 s each); {load['warmup_s']} s warm-up, "
        f"{load['duration_s']} s measured",
        "- Delivered: "
        + ", ".join(
            f"{k.replace('_rps', '')} {v:.2f} req/s"
            for k, v in report.get("achieved", {}).items()
            if v is not None
        ),
        "- Percentiles: nearest rank over every request of the measured window, "
        "failed requests included",
        "",
        "## Latency",
        "",
        "| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | Errors | Error rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group in GROUPS:
        g = report["requests"][group]
        lines.append(
            f"| {group} | {g['count']} | {_ms(g['p50_ms'])} | {_ms(g['p95_ms'])} | "
            f"{_ms(g['p99_ms'])} | {_ms(g['max_ms'])} | {g['errors']} | "
            f"{g['error_rate']:.2%} |"
        )
    by_endpoint = report["requests"].get("by_endpoint", {})
    if by_endpoint:
        lines += ["", "| Endpoint | Requests | p95 ms | Errors |", "| --- | --- | --- | --- |"]
        for name, g in by_endpoint.items():
            lines.append(f"| {name} | {g['count']} | {_ms(g['p95_ms'])} | {g['errors']} |")
    errors = report["requests"].get("errors_by_endpoint", {})
    if errors:
        lines += ["", "Errors: " + ", ".join(f"{k} x{v}" for k, v in sorted(errors.items()))]
    stops = report.get("blind_stops") or {}
    lines += [
        "",
        "Blind listens stopped by the server in the measured window: "
        + (", ".join(f"{k} x{v}" for k, v in sorted(stops.items())) or "none"),
        "",
        "## CPU (share of all host cores)",
        "",
        "| Role | Mean | p95 | Max | Samples |",
        "| --- | --- | --- | --- | --- |",
    ]
    for role, c in report["cpu"].items():
        lines.append(
            f"| {role} | {_pct(c['mean_pct'])} | {_pct(c['p95_pct'])} | "
            f"{_pct(c['max_pct'])} | {c['samples']} |"
        )
    targets = verdict_["targets"]
    checks = verdict_["checks"]
    lines += [
        "",
        "## Against System Design 1.1 and 12.1",
        "",
        "| Check | Target | Result |",
        "| --- | --- | --- |",
        f"| Read p95 | under {targets['read_p95_ms']:.0f} ms | "
        f"{'meets' if checks['read_p95'] else 'misses'} |",
        f"| Write p95 (heartbeats included) | under {targets['write_p95_ms']:.0f} ms | "
        f"{'meets' if checks['write_p95'] else 'misses'} |",
        f"| Server CPU (API + DB + worker), mean | under {targets['server_cpu_mean_pct']:.0f}% | "
        f"{'meets' if checks['cpu'] else 'misses'} |",
        "",
        "## Slowest statements (pg_stat_statements)",
        "",
        "| Calls | Total ms | Mean ms | Max ms | Rows | Query |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["statements"]["by_total"]:
        query = " ".join(r["query"].split())[:160].replace("|", "\\|")
        lines.append(
            f"| {r['calls']} | {r['total_ms']:.1f} | {r['mean_ms']:.2f} | {r['max_ms']:.1f} | "
            f"{r['rows']} | `{query}` |"
        )
    slow = report["statements"]["slow"]
    lines += [
        "",
        f"Statements with a mean of {SLOW_MEAN_MS:.0f} ms or more: "
        + (str(len(slow)) if slow else "none"),
    ]
    for r in slow:
        lines.append(
            f"- {r['mean_ms']:.1f} ms mean, {r['calls']} calls: "
            f"`{' '.join(r['query'].split())[:200]}`"
        )
    return "\n".join(lines) + "\n"


# Orchestration. Everything below drives Docker and the seeder; the decisions above are
# the tested part.

REPO = Path(__file__).resolve().parents[3]
STATEMENTS_SQL = """
SELECT coalesce(json_agg(s), '[]') FROM (
  SELECT query, calls, total_exec_time AS total_ms, mean_exec_time AS mean_ms,
         max_exec_time AS max_ms, rows, shared_blks_hit, shared_blks_read
  FROM pg_stat_statements
  WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
) s
"""


def _run(cmd: list[str], **kwargs: Any) -> str:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs).stdout


def _compose(args: argparse.Namespace) -> list[str]:
    cmd = ["docker", "compose", "-p", args.project]
    for file in args.compose_file:
        cmd += ["-f", str(file)]
    return cmd


def _psql(args: argparse.Namespace, sql: str) -> str:
    return _run(
        [
            *_compose(args),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "listenup",
            "-d",
            "listenup",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]
    )


def _wait_healthy(url: str, timeout_s: float = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"the API did not answer {url} within {timeout_s:.0f} s")
        time.sleep(2)


class StatsSampler:
    """Streams `docker stats` into (monotonic time, name, percent of one core) samples."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, str, float]] = []
        self._process = subprocess.Popen(
            ["docker", "stats", "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            for part in line.split("\x1b[H"):
                sample = parse_stats_line(part)
                if sample:
                    self.samples.append((time.monotonic(), *sample))

    def stop(self) -> None:
        self._process.terminate()
        self._process.wait(timeout=10)

    def between(self, start: float, end: float) -> list[tuple[str, float]]:
        return [(name, pct) for t, name, pct in self.samples if start <= t <= end]


def _environment(args: argparse.Namespace, cores: int) -> dict[str, Any]:
    sha = _run(["git", "-C", str(REPO), "rev-parse", "HEAD"]).strip()
    dirty = bool(_run(["git", "-C", str(REPO), "status", "--porcelain"]).strip())
    images = {}
    for service in ("api", "worker", "postgres"):
        container = f"{args.project}-{service}-1"
        images[service] = _run(["docker", "inspect", "-f", "{{.Image}}", container]).strip()
    return {
        "host": "stage-0" if args.stage0 else args.host_label,
        "git_sha": sha,
        "git_dirty": dirty,
        "cores": cores,
        "machine": machine_info(),
        "images": images,
        "k6_image": args.k6_image,
        "api_command": "uvicorn, one process, no reload (spikes/load/compose.b5.yml)",
        "seed": {
            "learners": args.learners,
            "history_clips": args.history,
            "blind_learners": args.blind_learners,
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not args.skip_up:
        _run([*_compose(args), "up", "-d", *([] if args.no_build else ["--build"]), *SERVICES])
    _wait_healthy(args.health_url)
    cores = int(_run(["docker", "info", "-f", "{{.NCPU}}"]).strip())

    manifest = out / "manifest.json"
    blind_sessions = math.ceil((args.warmup + args.duration) / 125) + 2
    _run(
        [
            "uv",
            "run",
            "python",
            "scripts/seed_load.py",
            "--learners",
            str(args.learners),
            "--history",
            str(args.history),
            "--blind-learners",
            str(args.blind_learners),
            "--blind-sessions",
            str(blind_sessions),
            "--database-url",
            args.database_url,
            "--out",
            str(manifest),
        ],
        cwd=REPO / "apps" / "api",
    )
    _psql(args, "CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

    sampler = StatsSampler()
    env = {
        "BASE_URL": args.base_url,
        "MANIFEST": "/out/manifest.json",
        "MIXED_RPS": args.mixed_rps,
        "BLIND_LEARNERS": args.blind_learners,
        "WARMUP_S": args.warmup,
        "DURATION_S": args.duration,
    }
    k6 = ["docker", "run", "--rm", "--name", K6_CONTAINER, "--network", f"{args.project}_default"]
    # As the caller, so k6 can read the private manifest and write next to it.
    k6 += ["--user", f"{os.getuid()}:{os.getgid()}"]
    k6 += ["-v", f"{REPO / 'spikes' / 'load'}:/scripts:ro", "-v", f"{out}:/out"]
    for name, value in env.items():
        k6 += ["-e", f"{name}={value}"]
    k6 += [args.k6_image, "run", "--quiet", "--out", "json=/out/k6.json", "/scripts/b5.js"]
    print("+ " + " ".join(k6), flush=True)
    started = time.monotonic()
    process = subprocess.Popen(k6)
    # k6 starts its clock about a second after the container; the measured window and
    # the statement reset follow the warm-up from here.
    try:
        process.wait(timeout=args.warmup + 1)
        sampler.stop()
        raise SystemExit("k6 ended during the warm-up; see its output above")
    except subprocess.TimeoutExpired:
        pass
    measure_start = time.monotonic()
    _psql(args, "SELECT pg_stat_statements_reset()")
    if process.wait() != 0:
        sampler.stop()
        raise SystemExit("k6 failed; see its output above")
    measure_end = min(time.monotonic(), measure_start + args.duration)
    sampler.stop()
    statements = json.loads(_psql(args, STATEMENTS_SQL) or "[]")

    k6_file = out / "k6.json"
    with k6_file.open() as lines:
        requests, stops = parse_k6_points(lines)
    with gzip.open(out / "requests.csv.gz", "wt", newline="") as raw:
        writer = csv.writer(raw)
        writer.writerow(["phase", "kind", "name", "status", "duration_ms", "error"])
        writer.writerows(astuple(r) for r in requests)
    k6_file.unlink()

    roles = {
        f"{args.project}-api-1": "api",
        f"{args.project}-postgres-1": "db",
        f"{args.project}-worker-1": "worker",
        K6_CONTAINER: "load",
    }
    summary = summarise_requests(requests)
    cpu = summarise_cpu(sampler.between(measure_start, measure_end), cores, roles)
    report = {
        "environment": _environment(args, cores),
        "load": {
            "mixed_rps": args.mixed_rps,
            "blind_learners": args.blind_learners,
            "warmup_s": args.warmup,
            "duration_s": args.duration,
            "elapsed_s": round(time.monotonic() - started, 1),
        },
        "requests": summary,
        "achieved": achieved_rates(summary, args.duration),
        "blind_stops": stops,
        "cpu": cpu,
        "statements": rank_statements(statements, args.top, args.slow_mean_ms),
        "verdict": verdict(summary, cpu, stage0=args.stage0),
    }
    (out / "results.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "results.md").write_text(render_markdown(report))
    manifest.unlink()  # holds session cookies; never kept with the results
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage0", action="store_true", help="the run is on the stage-0 server")
    parser.add_argument("--host-label", default="local Docker Compose")
    parser.add_argument("--learners", type=int, default=150)
    parser.add_argument("--history", type=int, default=10, help="extra clips per learner")
    parser.add_argument("--blind-learners", type=int, default=20)
    parser.add_argument("--mixed-rps", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--slow-mean-ms", type=float, default=SLOW_MEAN_MS)
    parser.add_argument("--project", default="listenup-b5")
    parser.add_argument(
        "--compose-file",
        type=Path,
        action="append",
        default=None,
        help="repeatable; default infra/compose/compose.yml and spikes/load/compose.b5.yml",
    )
    parser.add_argument("--skip-up", action="store_true", help="the stack is already running")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--base-url", default="http://api:8000", help="as k6 reaches the API")
    parser.add_argument("--health-url", default="http://localhost:8000/api/v1/health")
    parser.add_argument(
        "--database-url",
        default="postgresql://listenup:listenup@localhost:55432/listenup",
        help="the database owner, for seeding",
    )
    parser.add_argument("--k6-image", default=K6_IMAGE)
    args = parser.parse_args(argv)
    if args.blind_learners > args.learners:
        parser.error("--blind-learners cannot exceed --learners")
    args.compose_file = args.compose_file or [
        REPO / "infra" / "compose" / "compose.yml",
        REPO / "spikes" / "load" / "compose.b5.yml",
    ]
    report = run(args)
    print(render_markdown(report))
    sys.exit(0 if report["verdict"]["meets_targets"] else 1)


if __name__ == "__main__":
    main()
