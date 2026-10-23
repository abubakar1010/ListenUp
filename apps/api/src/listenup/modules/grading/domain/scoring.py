"""Deterministic, versioned comprehension scoring (FR-BL-7, D3)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DIMENSIONS = frozenset({"main_idea", "key_details", "accuracy"})


@dataclass(frozen=True)
class Rubric:
    version: str
    weights: Mapping[str, int]
    levels: Mapping[str, int]

    @classmethod
    def load(cls, path: Path) -> "Rubric":
        data = json.loads(path.read_text(encoding="utf-8"))
        weights, levels = data["weights"], data["levels"]
        if (
            not isinstance(data["version"], str)
            or not data["version"]
            or set(weights) != DIMENSIONS
            or any(type(w) is not int or w <= 0 for w in weights.values())
            or sum(weights.values()) != 100
            or set(levels) != {"fair", "good", "excellent"}
            or any(type(n) is not int for n in levels.values())
            or not 0 < levels["fair"] < levels["good"] < levels["excellent"] <= 100
        ):
            raise ValueError("Invalid grading rubric")
        return cls(data["version"], weights, levels)

    def score(self, dimensions: Mapping[str, int]) -> int:
        if set(dimensions) != DIMENSIONS or any(
            type(n) is not int or not 0 <= n <= 100 for n in dimensions.values()
        ):
            raise ValueError("Invalid dimension scores")
        # Positive integer arithmetic: nearest integer, halves rounded up.
        return (sum(dimensions[k] * self.weights[k] for k in DIMENSIONS) + 50) // 100

    def level(self, score: int) -> str:
        if type(score) is not int or not 0 <= score <= 100:
            raise ValueError("Invalid overall score")
        for name in ("excellent", "good", "fair"):
            if score >= self.levels[name]:
                return name
        return "needs_work"
