"""Compare word timings from several sources (B1 timestamps, B2 aligners, hand labels).

Usage:
    spike-compare results/words --labels ../docs/spikes/b2-labels --out results/
results/words/<source>/<passage>.json are written by spike-b1 and spike-b2 (`window`
and `words` in the passage file's time). Hand labels are NAME.labels.csv
(word,start_s,end_s, in the same time), from `spike-labelkit import`.

Two tables:
- against hand labels (only for the labelled windows): the boundary error of each source;
- agreement between sources (every passage): how far two systems' boundaries are apart.
  Agreement is a proxy, not accuracy: two systems can agree and both be wrong.
"""

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

from listenup_spikes.common import Report
from listenup_spikes.metrics import boundary_errors_ms, spread

Words = list[tuple[str, float, float]]


def load_source(folder: Path) -> dict[str, Words]:
    """Passage name to the words inside its passage window."""
    out = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text())
        start, end = data["window"]
        out[path.stem] = [
            (w["word"], w["start"], w["end"])
            for w in data["words"]
            if start <= (w["start"] + w["end"]) / 2 < end
        ]
    return out


def load_labels(folder: Path) -> dict[str, Words]:
    out = {}
    for path in sorted(folder.glob("*.labels.csv")):
        with path.open() as f:
            out[path.name.removesuffix(".labels.csv")] = [
                (w, float(s), float(e)) for w, s, e in csv.reader(f)
            ]
    return out


def _row(
    name: str, errors: list[float], words: int, *, hand_labels: bool = False
) -> dict[str, object]:
    s = spread(errors) if errors else None
    matched = len(errors) // 2
    row: dict[str, object] = {
        "comparison": name,
        "words_matched": matched,
        "words_compared": words,
        "words_unmatched": words - matched,
        "coverage": round(matched / words, 3) if words else 0.0,
        "mean_ms": round(s.mean, 1) if s else None,
        "median_ms": round(s.median, 1) if s else None,
        "p90_ms": round(s.p90, 1) if s else None,
        # Shares use ALL compared boundaries, so dropping a word cannot improve them.
        "within_50ms": round(sum(e <= 50 for e in errors) / (2 * words), 3) if words else 0.0,
        "within_100ms": round(sum(e <= 100 for e in errors) / (2 * words), 3) if words else 0.0,
    }
    if hand_labels:
        row["meets_hand_label_gate"] = bool(s and matched == words and s.mean <= 50)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("words", type=Path)
    parser.add_argument("--sources", nargs="+", help="subfolders to compare (default: all)")
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--only", help="compare only passages whose name starts with this")
    parser.add_argument("--name", default="spike-19-b2-boundaries", help="report file name")
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    names = args.sources or sorted(p.name for p in args.words.iterdir() if p.is_dir())
    sources = {
        name: {
            passage: words
            for passage, words in load_source(args.words / name).items()
            if not args.only or passage.startswith(args.only)
        }
        for name in names
    }
    columns = [
        "comparison",
        "words_matched",
        "words_compared",
        "words_unmatched",
        "coverage",
        "mean_ms",
        "median_ms",
        "p90_ms",
        "within_50ms",
        "within_100ms",
        "meets_hand_label_gate",
    ]
    report = Report(args.name, columns)
    report.summary["passages"] = args.only or "all"

    labels = {
        passage: words
        for passage, words in (load_labels(args.labels) if args.labels else {}).items()
        if not args.only or passage.startswith(args.only)
    }
    report.summary["hand-labelled windows"] = len(labels)
    report.summary["boundary_matching"] = "ordered text blocks; no timing cutoff; v2"
    report.summary["hand_label_gate"] = (
        "all labelled words matched and mean boundary error <= 50 ms"
    )
    for name, words_of in sources.items():
        errors, compared = [], 0
        for passage, labelled in labels.items():
            errors += boundary_errors_ms(words_of.get(passage, []), labelled)
            compared += len(labelled)
        if args.labels:
            report.add(**_row(f"{name} vs hand labels", errors, compared, hand_labels=True))
    for a, b in combinations(names, 2):
        errors, compared = [], 0
        for passage in sorted(sources[b]):
            errors += boundary_errors_ms(sources[a].get(passage, []), sources[b][passage])
            compared += len(sources[b][passage])
        if compared:
            report.add(**_row(f"{a} vs {b} (agreement)", errors, compared))
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
