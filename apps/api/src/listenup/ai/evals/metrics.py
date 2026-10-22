"""Metrics compare all three attempts with references, with explicit denominators."""

from collections.abc import Sequence
from statistics import mean

from listenup.ai.evals.models import Grade


def summarize(rows: Sequence[tuple[Grade, Sequence[Grade]]]) -> dict[str, float]:
    if not rows or any(len(runs) != 3 for _, runs in rows):
        raise ValueError("metrics require nonempty cases with three successful runs each")
    names = set(rows[0][0].scores)
    if any(
        set(grade.scores) != names
        or (grade.level is None) != (expected.level is None)
        or (grade.filler_count is None) != (expected.filler_count is None)
        for expected, runs in rows
        for grade in (expected, *runs)
    ):
        raise ValueError("incomplete or incompatible grades")
    metrics: dict[str, float] = {}
    for name in sorted(names | {"overall"}):
        values = [
            (expected.overall, [g.overall for g in runs])
            if name == "overall"
            else (expected.scores[name], [g.scores[name] for g in runs])
            for expected, runs in rows
        ]
        metrics[f"mae.{name}"] = mean(abs(v - ref) for ref, scores in values for v in scores)
        metrics[f"max_range.{name}"] = max(max(scores) - min(scores) for _, scores in values)
    if rows[0][0].level is not None:
        metrics["level_agreement"] = mean(
            float(g.level == expected.level) for expected, runs in rows for g in runs
        )
    if rows[0][0].filler_count is not None:
        errors = [
            abs(g.filler_count - expected.filler_count)
            for expected, runs in rows
            for g in runs
            if g.filler_count is not None and expected.filler_count is not None
        ]
        metrics["filler_count_mae"] = mean(errors)
        metrics["filler_count_max_error"] = float(max(errors))
    return metrics
