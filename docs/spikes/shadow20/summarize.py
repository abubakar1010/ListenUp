"""Print auditable per-pair tables and win counts; no inferred pass on missing values."""

import argparse
import json
from pathlib import Path

from measures import filler_count

MEASURES = [
    "timing",
    "pronunciation",
    "accent",
    "articulation",
    "fluency",
    "fillers",
    "completeness",
]


def wins(good, poor):
    return [
        k
        for k in MEASURES
        if good[k] is not None and poor[k] is not None and good[k] > poor[k]
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fp32", type=Path)
    parser.add_argument("int8", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.fp32.read_text())
    quant = json.loads(args.int8.read_text())
    assert len(rows) == len(quant) == 10
    fmt = lambda v: "missing" if v is None else f"{v:.1f}"
    for row, q in zip(rows, quant, strict=True):
        assert row["pair"] == q["pair"] and row["hashes"] == q["hashes"]
        g, p = [row["recordings"][r]["scores"] for r in ["good", "poor"]]
        qg, qp = [q["recordings"][r]["scores"] for r in ["good", "poor"]]
        print(
            f"\n### Pair {row['pair']}: {row['prompt']} ({row['original_speaker']} → {row['good_speaker']})\n"
        )
        print(
            f"Removed word: `{row['skipped_word']}`. Strict good > poor: **{len(wins(g, p))}/7** (fp32), **{len(wins(qg, qp))}/7** (int8).\n"
        )
        print(
            "| Measure | Good fp32 | Poor fp32 | Good int8 | Poor int8 |\n| --- | ---: | ---: | ---: | ---: |"
        )
        for k in MEASURES:
            print(
                "| " + k + " | " + " | ".join(fmt(s[k]) for s in [g, p, qg, qp]) + " |"
            )
    print("\n## Aggregate strict wins\n")
    print(
        "| Measure | fp32 wins / ties / missing | int8 wins / ties / missing |\n| --- | --- | --- |"
    )
    for k in MEASURES:
        values = []
        for rr in [rows, quant]:
            pairs = [
                (
                    r["recordings"]["good"]["scores"][k],
                    r["recordings"]["poor"]["scores"][k],
                )
                for r in rr
            ]
            values.append(
                " / ".join(
                    str(n)
                    for n in [
                        sum(a > b for a, b in pairs if a is not None and b is not None),
                        sum(
                            a == b for a, b in pairs if a is not None and b is not None
                        ),
                        sum(a is None or b is None for a, b in pairs),
                    ]
                )
            )
        print(f"| {k} | {values[0]} | {values[1]} |")
    print("\n## Single-degradation controls (fp32)\n")
    print(
        "| Pair | Variant | Timing | GOP pronunciation | Articulation | Fluency | Fillers | Completeness |\n| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for row in rows[:2]:
        for name in ["good", "late", "lowpass", "skip", "fill", "poor"]:
            scores = row["recordings"][name]["scores"]
            print(
                "| "
                + row["pair"]
                + " | "
                + name
                + " | "
                + " | ".join(fmt(scores[k]) for k in MEASURES if k != "accent")
                + " |"
            )
    print("\n## Echo controls (threshold 0.6)\n")
    print(
        "| Pair | Independent clean reading | Exact copy | Digital mixture |\n| --- | ---: | ---: | ---: |"
    )
    for row in rows:
        c = row["echo_controls"]
        print(
            "| "
            + row["pair"]
            + " | "
            + " | ".join(f"{c[k]:.3f}" for k in ["clean", "copy", "mixed"])
            + " |"
        )
    print("\n## Filler counts (fp32; poor has 2 intended synthetic insertions)\n")
    print("| Pair | Original | Good | Poor |\n| --- | ---: | ---: | ---: |")
    for row in rows:
        print(
            f"| {row['pair']} | {filler_count(row['reference']['transcript'])} | {row['recordings']['good']['filler_count']} | {row['recordings']['poor']['filler_count']} |"
        )


if __name__ == "__main__":
    main()
