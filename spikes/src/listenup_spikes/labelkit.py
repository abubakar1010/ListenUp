"""Hand-labelling kit for the B2 word-boundary check (Praat TextGrids).

Make the kit (TextGrid templates are committed; the window audio is not):
    spike-labelkit make data/passages ../docs/spikes/b2-labels/windows.json \\
        --audio-out data/labels
Label: open data/labels/NAME.wav with ../docs/spikes/b2-labels/NAME.TextGrid in Praat and
mark every word in the `words` tier (see docs/spikes/b2-labels/README.md).
Import:
    spike-labelkit import ../docs/spikes/b2-labels/windows.json ../docs/spikes/b2-labels

The `hint` tier holds the reference text of the utterances that overlap the window (their
times are known from how the passage was built), as text only: nothing from any model
reaches the labeller, so the labels are independent of every system they measure.
"""

import argparse
import csv
import json
import re
from pathlib import Path

SAMPLE_RATE = 16000


def textgrid(duration: float, hint: str) -> str:
    """A long-format TextGrid with an empty `words` tier and a `hint` tier."""

    def tier(name: str, text: str) -> str:
        escaped = text.replace('"', '""')
        return (
            '        class = "IntervalTier"\n'
            f'        name = "{name}"\n'
            "        xmin = 0\n"
            f"        xmax = {duration}\n"
            "        intervals: size = 1\n"
            "        intervals [1]:\n"
            "            xmin = 0\n"
            f"            xmax = {duration}\n"
            f'            text = "{escaped}"\n'
        )

    return (
        'File type = "ooTextFile"\nObject class = "TextGrid"\n\n'
        f"xmin = 0\nxmax = {duration}\ntiers? <exists>\nsize = 2\nitem []:\n"
        f"    item [1]:\n{tier('words', '')}    item [2]:\n{tier('hint', hint)}"
    )


_INTERVAL = re.compile(
    r'xmin = (?P<xmin>[0-9.eE+-]+)\s+xmax = (?P<xmax>[0-9.eE+-]+)\s+text = "(?P<text>(?:[^"]|"")*)"'
)


def read_tier(content: str, name: str) -> list[tuple[str, float, float]]:
    """The non-empty intervals of one interval tier of a long-format TextGrid."""
    items = re.split(r"\n\s*item \[\d+\]:", content)
    for item in items[1:]:
        if re.search(rf'name = "{re.escape(name)}"', item):
            return [
                (m["text"].replace('""', '"').strip(), float(m["xmin"]), float(m["xmax"]))
                for m in _INTERVAL.finditer(item)
                if m["text"].strip()
            ]
    raise ValueError(f"no tier named {name!r}")


def window_hint(segments: list[dict[str, object]], start: float, end: float) -> str:
    """Reference text of the segments that overlap [start, end)."""
    return " ".join(
        str(s["text"])
        for s in segments
        if float(str(s["start"])) < end and float(str(s["end"])) > start
    )


def make(passages: Path, windows: Path, audio_out: Path) -> None:
    import soundfile as sf

    from listenup_spikes.media import decode

    spec = json.loads(windows.read_text())
    audio_out.mkdir(parents=True, exist_ok=True)
    for name, window in spec["windows"].items():
        start, seconds = float(window["start_s"]), float(window["seconds"])
        audio = decode(passages / f"{window['passage']}.wav")
        clip = audio[round(start * SAMPLE_RATE) : round((start + seconds) * SAMPLE_RATE)]
        sf.write(audio_out / f"{name}.wav", clip, SAMPLE_RATE, subtype="PCM_16")
        meta = json.loads((passages / f"{window['passage']}.json").read_text())
        hint = window_hint(meta["segments"], start, start + seconds)
        grid = windows.parent / f"{name}.TextGrid"
        if not grid.exists():  # never overwrite a labelled grid
            grid.write_text(textgrid(seconds, hint))
        print(f"wrote {audio_out / name}.wav and {grid}")


def import_labels(windows: Path, out: Path) -> None:
    spec = json.loads(windows.read_text())
    for name, window in spec["windows"].items():
        grid = windows.parent / f"{name}.TextGrid"
        labelled = read_tier(grid.read_text(), "words")
        if not labelled:
            print(f"{grid.name}: no words labelled yet")
            continue
        start = float(window["start_s"])
        path = out / f"{window['passage']}.labels.csv"
        with path.open("w", newline="") as f:
            csv.writer(f).writerows(
                (w, round(s + start, 3), round(e + start, 3)) for w, s, e in labelled
            )
        print(f"wrote {path} ({len(labelled)} words)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("passages", type=Path)
    mk.add_argument("windows", type=Path)
    mk.add_argument("--audio-out", type=Path, default=Path("data/labels"))
    im = sub.add_parser("import")
    im.add_argument("windows", type=Path)
    im.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "make":
        make(args.passages, args.windows, args.audio_out)
    else:
        import_labels(args.windows, args.out)


if __name__ == "__main__":
    main()
