"""Compare word timings from several sources (B1 timestamps, B2 aligners, hand labels).

Usage:
    spike-compare results/words --labels ../docs/spikes/b2-labels --out results/
results/words/<source>/<passage>.json are written by spike-b1 and spike-b2 (`window`
and `words` in the passage file's time). Hand labels are WINDOW.labels.csv
(passage,word,start_s,end_s, in the same time), from `spike-labelkit import`.

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
    """Passage name to its hand-labelled words, from every labelled window in it."""
    out: dict[str, Words] = {}
    for path in sorted(folder.glob("*.labels.csv")):
        with path.open() as f:
            for passage, w, s, e in csv.reader(f):
                out.setdefault(passage, []).append((w, float(s), float(e)))
    return {passage: sorted(words, key=lambda w: w[1]) for passage, words in out.items()}


def _row(name: str, errors: list[float], words: int) -> dict[str, object]:
    s = spread(errors)
    return {
        "comparison": name,
        "words_matched": s.count // 2,
        "words_compared": words,
        "mean_ms": round(s.mean, 1),
        "median_ms": round(s.median, 1),
        "p90_ms": round(s.p90, 1),
        "within_50ms": round(s.share_within_50ms, 3),
        "within_100ms": round(s.share_within_100ms, 3),
    }


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
        "mean_ms",
        "median_ms",
        "p90_ms",
        "within_50ms",
        "within_100ms",
    ]
    report = Report(args.name, columns)
    report.summary["passages"] = args.only or "all"

    labels = load_labels(args.labels) if args.labels else {}
    windows = len(list(args.labels.glob("*.labels.csv"))) if args.labels else 0
    report.summary["hand-labelled windows"] = windows
    for name, words_of in sources.items():
        errors, compared = [], 0
        for passage, labelled in labels.items():
            if passage in words_of:
                errors += boundary_errors_ms(words_of[passage], labelled)
                compared += len(labelled)
        if errors:
            report.add(**_row(f"{name} vs hand labels", errors, compared))
    for a, b in combinations(names, 2):
        errors, compared = [], 0
        for passage in sorted(set(sources[a]) & set(sources[b])):
            errors += boundary_errors_ms(sources[a][passage], sources[b][passage])
            compared += len(sources[b][passage])
        if errors:
            report.add(**_row(f"{a} vs {b} (agreement)", errors, compared))
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
