"""Dependency-free B3 workload and reporting rules."""

import math


def pack(items, count=30, target=75):
    rounds, current, duration = [], [], 0
    for name, seconds in items:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Invalid source duration")
        current.append((name, seconds))
        duration += seconds
        if duration >= target:
            rounds.append(current)
            current, duration = [], 0
            if len(rounds) == count:
                return rounds
    raise ValueError("Insufficient public audio for requested rounds")


def windows(speech, rate, seconds=30):
    result = []
    for span in speech:
        for start in range(span["start"], span["end"], rate * seconds):
            result.append((start, min(start + rate * seconds, span["end"])))
    return result


def summary(values):
    if len(values) != 30 or any(not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError("A complete run needs 30 positive finite latencies")
    ordered = sorted(values)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return dict(
        label="CI-runner evidence (E4)",
        count=30,
        percentile_method="nearest rank",
        p50_s=ordered[14],
        p95_s=p95,
        range_s=[ordered[0], ordered[-1]],
        spread_s=ordered[-1] - ordered[0],
        **{"pass": p95 < 50},
    )


def validate_budget(cpu, memory, swap, threads, interop):
    quota, period = cpu.split()
    if (
        quota == "max"
        or int(quota) != 2 * int(period)
        or memory != "8589934592"
        or swap != "0"
        or threads != 2
        or interop != 2
    ):
        raise ValueError("E4 requires two CPUs/threads, 8 GiB and no swap")
