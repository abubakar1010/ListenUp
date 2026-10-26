"""B5 (#94): load-test the API and Blind heartbeats, and report against System Design 1.1.

Starts the stack (infra/compose/compose.yml with spikes/load/compose.b5.yml), seeds N
learners with apps/api/scripts/seed_load.py, runs spikes/load/b5.js in the pinned k6
image, samples `docker stats` for CPU and dumps the heaviest pg_stat_statements entries.

    spike-b5 --out results/b5-local                # local: labelled as not stage-0
    spike-b5 --stage0 --skip-up --base-url ... --out results/b5-stage0   # stage-0 only

Percentiles are nearest-rank over every request of the measured window, failed
requests included. CPU is each container's share of all host cores. Writes
results.json, results.md and requests.csv.gz (one line per request) in --out. The seed
manifest (session tokens) lives in a private temporary folder for the run only, and
the seeded learners are deleted afterwards unless --keep-data is given.
"""

import argparse
import csv
import gzip
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
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
# A run is only a pass if its requests were answered and its load was sent (#155: failed
# requests stay in the outcome). Proposed in ADR 0065, pending the owner's confirmation:
# reads and writes each fail under 1% of the time, and at least 95% of the planned mixed
# and heartbeat rates is delivered.
MAX_ERROR_RATE = 0.01
MIN_DELIVERED = 0.95

LOCAL_LABEL = "Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)"
STAGE0_LABEL = "Stage-0 server run (#16): qualifies for #155 after independent review"

K6_IMAGE = "grafana/k6:1.3.0"
LOCAL_BASE_URL = "http://api:8000"
HEARTBEAT_S = 5
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
    # Fast failures pull a percentile down; this shows by how much.
    answered = [r.duration_ms for r in requests if r.status != 0]
    errors = sum(1 for r in requests if _is_error(r.status))
    return {
        "count": len(requests),
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "max_ms": max(durations) if durations else None,
        "p50_answered_ms": percentile(answered, 0.50),
        "p95_answered_ms": percentile(answered, 0.95),
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
    worker summed per sampling round (each round has one sample per container); a round
    without every server container would understate it, so it is left out and counted.
    The load generator (`load`) is reported but is not part of the server."""
    per_role: dict[str, list[float]] = {role: [] for role in roles.values()}
    server_names = {name for name, role in roles.items() if role != "load"}
    rounds: list[float] = []
    incomplete = 0
    seen: set[str] = set()
    current = 0.0

    def close_round() -> None:
        nonlocal incomplete
        if server_names <= seen:
            rounds.append(current)
        else:
            incomplete += 1

    for name, pct in samples:
        role = roles.get(name)
        if role is None:
            continue
        if name in seen:  # a container repeats: the previous round is over
            close_round()
            seen, current = set(), 0.0
        seen.add(name)
        per_role[role].append(pct)
        if role != "load":
            current += pct
    if seen:
        close_round()
    result = {role: _cpu(values, cores) for role, values in per_role.items()}
    result["server"] = {**_cpu(rounds, cores), "incomplete_rounds": incomplete}
    return result


def measured_window(start_at: float, warmup_s: float, duration_s: float) -> tuple[float, float]:
    """The measured window in wall-clock seconds. k6 waits for `start_at` before its
    scenarios begin, so the statement reset and the CPU window follow the same clock."""
    return start_at + warmup_s, start_at + warmup_s + duration_s


def summarise_attempts(rows: Iterable[tuple[str, str | None, int]]) -> dict[str, Any]:
    """The Blind attempts of the run by outcome (listened, unfinished, submitted), with
    voids by reason. An unfinished attempt at the end of the run is one whose listen
    k6 did not see through, such as an `ended` beat that got no answer."""
    result: dict[str, Any] = {"voided": {}}
    for outcome, reason, count in rows:
        if outcome == "voided":
            key = reason or "unknown"
            result["voided"][key] = result["voided"].get(key, 0) + count
        else:
            result[outcome] = result.get(outcome, 0) + count
    if not result["voided"]:
        del result["voided"]
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


def verdict(
    summary: dict[str, Any],
    cpu: dict[str, Any],
    achieved: dict[str, float | None],
    planned: dict[str, float],
    *,
    stage0: bool,
) -> dict[str, Any]:
    """Against System Design 1.1 and 12.1, for a run whose requests were answered and
    whose load was delivered. A missing measurement fails its check."""

    def under(value: float | None, limit: float) -> bool:
        return value is not None and value < limit

    def delivered(name: str) -> bool:
        value = achieved.get(name)
        # The tolerance only absorbs float rounding of the 95% share itself.
        return value is not None and value >= MIN_DELIVERED * planned[name] - 1e-9

    checks = {
        "read_p95": under(summary["read"]["p95_ms"], READ_P95_MS),
        "write_p95": under(summary["write"]["p95_ms"], WRITE_P95_MS),
        "cpu": under(cpu["server"]["mean_pct"], CPU_LIMIT_PCT),
        "errors": all(
            under(summary[group]["error_rate"], MAX_ERROR_RATE) for group in ("read", "write")
        ),
        "delivered": all(delivered(name) for name in planned),
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
            "max_error_rate": MAX_ERROR_RATE,
            "min_delivered_share": MIN_DELIVERED,
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
        "| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | p95 answered ms | Errors "
        "| Error rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group in GROUPS:
        g = report["requests"][group]
        lines.append(
            f"| {group} | {g['count']} | {_ms(g['p50_ms'])} | {_ms(g['p95_ms'])} | "
            f"{_ms(g['p99_ms'])} | {_ms(g['max_ms'])} | {_ms(g.get('p95_answered_ms'))} | "
            f"{g['errors']} | {g['error_rate']:.2%} |"
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
    ]
    attempts = report.get("blind_attempts")
    if attempts is not None:
        outcomes = [f"{k} x{v}" for k, v in sorted(attempts.items()) if k != "voided"]
        outcomes += [f"voided {k} x{v}" for k, v in sorted(attempts.get("voided", {}).items())]
        lines.append(
            "Blind attempts of the run at its end, by outcome: " + (", ".join(outcomes) or "none")
        )
    lines += [
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
        f"| Error rate, reads and writes each | under {targets['max_error_rate']:.0%} | "
        f"{'meets' if checks['errors'] else 'misses'} |",
        f"| Delivered load | at least {targets['min_delivered_share']:.0%} of the plan | "
        f"{'meets' if checks['delivered'] else 'misses'} |",
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


# Orchestration. Everything below drives Docker, the database and the seeder; the
# decisions above are the tested part, with private_manifest and parse_args.

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
STATEMENTS_SQL = """
SELECT coalesce(json_agg(s), '[]') FROM (
  SELECT query, calls, total_exec_time AS total_ms, mean_exec_time AS mean_ms,
         max_exec_time AS max_ms, rows, shared_blks_hit, shared_blks_read
  FROM pg_stat_statements
  WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
) s
"""
# The Blind sessions' attempts by outcome; a listen is complete within 1 s of the
# passage end (END_TOLERANCE_MS in modules/blind/domain/listen.py).
ATTEMPTS_SQL = """
SELECT CASE
         WHEN a.status = 'voided' THEN 'voided'
         WHEN a.status = 'submitted' THEN 'submitted'
         WHEN b.last_position_ms >= b.passage_end_ms - 1000 THEN 'listened'
         ELSE 'unfinished'
       END AS outcome,
       b.void_reason,
       count(*)
FROM practice.attempts a JOIN practice.blind_attempts b ON b.attempt_id = a.id
WHERE a.session_id = ANY(%s::uuid[])
GROUP BY 1, 2
"""


@contextmanager
def private_manifest() -> Iterator[Path]:
    """Where the seed manifest (session tokens) lives for one run: a folder only the
    caller can read, outside --out, removed however the run ends."""
    folder = Path(tempfile.mkdtemp(prefix="listenup-b5-"))  # mode 0700
    try:
        yield folder / "manifest.json"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(cmd: list[str], **kwargs: Any) -> str:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs).stdout


def _compose(args: argparse.Namespace) -> list[str]:
    cmd = ["docker", "compose", "-p", args.project]
    for file in args.compose_file:
        cmd += ["-f", str(file)]
    return cmd


def _sql(args: argparse.Namespace, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    """Run one statement as the database owner (--database-url), here or on stage 0."""
    import psycopg  # the `load` extra

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        cursor = conn.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


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
    """Streams `docker stats` into (wall-clock time, name, percent of one core) samples."""

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
                    self.samples.append((time.time(), *sample))

    def stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=10)

    def between(self, start: float, end: float) -> list[tuple[str, float]]:
        return [(name, pct) for t, name, pct in self.samples if start <= t <= end]


def _optional(cmd: list[str]) -> str | None:
    """Output of a command that may not apply on this host (e.g. no local containers)."""
    try:
        return _run(cmd).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _environment(args: argparse.Namespace, cores: int) -> dict[str, Any]:
    sha = _run(["git", "-C", str(REPO), "rev-parse", "HEAD"]).strip()
    dirty = bool(_run(["git", "-C", str(REPO), "status", "--porcelain"]).strip())
    images = {
        service: _optional(["docker", "inspect", "-f", "{{.Image}}", f"{args.project}-{service}-1"])
        for service in ("api", "worker", "postgres")
    }
    return {
        "host": args.host_label,
        "hostname": socket.gethostname(),
        "base_url": args.base_url,
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


def _seed_script(args: argparse.Namespace, *options: str) -> None:
    _run(
        ["uv", "run", "python", "scripts/seed_load.py", "--database-url", args.database_url]
        + list(options),
        cwd=API,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not args.skip_up:
        _run([*_compose(args), "up", "-d", *([] if args.no_build else ["--build"]), *SERVICES])
    _wait_healthy(args.health_url)
    cores = args.cores or int(_run(["docker", "info", "-f", "{{.NCPU}}"]).strip())
    # Pulled before the clock starts, so a download cannot eat into the warm-up.
    _run(["docker", "pull", args.k6_image])

    with private_manifest() as manifest:
        blind_sessions = math.ceil((args.warmup + args.duration) / 125) + 2
        try:
            _seed_script(
                args,
                *("--learners", str(args.learners), "--history", str(args.history)),
                *("--blind-learners", str(args.blind_learners)),
                *("--blind-sessions", str(blind_sessions), "--out", str(manifest)),
            )
            return _measure(args, out, manifest, cores)
        finally:
            if manifest.exists() and not args.keep_data:
                # The seeded learners and their login sessions go with the run.
                _seed_script(args, "--delete-from", str(manifest))


def _measure(args: argparse.Namespace, out: Path, manifest: Path, cores: int) -> dict[str, Any]:
    _sql(args, "CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    sampler = StatsSampler()
    try:
        # k6 waits in setup() until start_at, so the measured window is known in advance
        # and does not depend on how long the container takes to start.
        start_at = time.time() + args.start_lead
        measure_start, measure_end = measured_window(start_at, args.warmup, args.duration)
        env = {
            "BASE_URL": args.base_url,
            "MANIFEST": "/secrets/manifest.json",
            "MIXED_RPS": args.mixed_rps,
            "BLIND_LEARNERS": args.blind_learners,
            "WARMUP_S": args.warmup,
            "DURATION_S": args.duration,
            "START_AT_MS": int(start_at * 1000),
        }
        k6 = ["docker", "run", "--rm", "--name", K6_CONTAINER]
        network = args.k6_network or (None if args.skip_up else f"{args.project}_default")
        if network:
            k6 += ["--network", network]
        # As the caller, so k6 can read the private manifest and write the results.
        k6 += ["--user", f"{os.getuid()}:{os.getgid()}"]
        k6 += ["-v", f"{REPO / 'spikes' / 'load'}:/scripts:ro", "-v", f"{out}:/out"]
        k6 += ["-v", f"{manifest.parent}:/secrets:ro"]
        for name, value in env.items():
            k6 += ["-e", f"{name}={value}"]
        k6 += [args.k6_image, "run", "--quiet", "--out", "json=/out/k6.json", "/scripts/b5.js"]
        print("+ " + " ".join(k6), flush=True)
        process = subprocess.Popen(k6)
        try:
            process.wait(timeout=max(0.0, measure_start - time.time()))
            raise SystemExit("k6 ended before the measured window; see its output above")
        except subprocess.TimeoutExpired:
            pass
        _sql(args, "SELECT pg_stat_statements_reset()")
        if process.wait() != 0:
            raise SystemExit("k6 failed; see its output above")
    finally:
        sampler.stop()
    statements = _sql(args, STATEMENTS_SQL)[0][0]
    blind_ids = [
        sid
        for learner in json.loads(manifest.read_text())["learners"]
        for sid in learner["blind_sessions"]
    ]
    attempts = summarise_attempts(_sql(args, ATTEMPTS_SQL, [blind_ids]))

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
    achieved = achieved_rates(summary, args.duration)
    planned = {
        "mixed_rps": float(args.mixed_rps),
        "heartbeat_rps": args.blind_learners / HEARTBEAT_S,
    }
    report = {
        "environment": _environment(args, cores),
        "load": {
            "mixed_rps": args.mixed_rps,
            "blind_learners": args.blind_learners,
            "warmup_s": args.warmup,
            "duration_s": args.duration,
            "measured_from": measure_start,
            "measured_to": measure_end,
        },
        "requests": summary,
        "achieved": achieved,
        "planned": planned,
        "blind_stops": stops,
        "blind_attempts": attempts,
        "cpu": cpu,
        "statements": rank_statements(statements, args.top, args.slow_mean_ms),
        "verdict": verdict(summary, cpu, achieved, planned, stage0=args.stage0),
    }
    (out / "results.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "results.md").write_text(render_markdown(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--stage0",
        action="store_true",
        help="the run is on the stage-0 deployment; needs --skip-up and its --base-url",
    )
    parser.add_argument("--host-label", default=None, help="default: local or stage-0")
    parser.add_argument("--learners", type=int, default=150)
    parser.add_argument("--history", type=int, default=10, help="extra clips per learner")
    parser.add_argument("--blind-learners", type=int, default=20)
    parser.add_argument("--mixed-rps", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument(
        "--start-lead", type=float, default=20.0, help="seconds k6 has to start before the clock"
    )
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
    parser.add_argument("--base-url", default=LOCAL_BASE_URL, help="as k6 reaches the API")
    parser.add_argument("--health-url", default="http://localhost:8000/api/v1/health")
    parser.add_argument(
        "--database-url",
        default="postgresql://listenup:listenup@localhost:55432/listenup",
        help="the database owner: seeding, pg_stat_statements and the attempt outcomes",
    )
    parser.add_argument("--cores", type=int, default=None, help="server cores; default docker info")
    parser.add_argument(
        "--keep-data", action="store_true", help="keep the seeded learners after the run"
    )
    parser.add_argument("--k6-image", default=K6_IMAGE)
    parser.add_argument(
        "--k6-network", default=None, help="docker network for k6; default the Compose project's"
    )
    args = parser.parse_args(argv)
    if args.blind_learners > args.learners:
        parser.error("--blind-learners cannot exceed --learners")
    if args.stage0 and (not args.skip_up or args.base_url == LOCAL_BASE_URL):
        parser.error("--stage0 runs against the deployed stack: give --skip-up and --base-url")
    args.host_label = args.host_label or (
        f"stage-0 ({socket.gethostname()})" if args.stage0 else "local Docker Compose"
    )
    args.compose_file = args.compose_file or [
        REPO / "infra" / "compose" / "compose.yml",
        REPO / "spikes" / "load" / "compose.b5.yml",
    ]
    return args


def main(argv: list[str] | None = None) -> None:
    report = run(parse_args(argv))
    print(render_markdown(report))
    sys.exit(0 if report["verdict"]["meets_targets"] else 1)


if __name__ == "__main__":
    main()
