"""Build B1/B2 test passages from LibriSpeech test-clean (public domain, openslr.org/12).

Usage:
    curl -LO https://www.openslr.org/resources/12/test-clean.tar.gz && tar xzf test-clean.tar.gz
    spike-librispeech LibriSpeech/test-clean data/passages --count 20 --seconds 180
Each chapter's utterances are joined in order until the passage reaches the target length,
giving NAME.wav plus NAME.txt with the exact reference text. Read speech is easier than
YouTube speech, so also add a few real clips with hand-checked text before deciding (B1).
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from listenup_spikes.media import duration_s


def read_transcripts(chapter: Path) -> list[tuple[Path, str]]:
    """Utterances of one chapter, in order: (flac path, text)."""
    trans = next(chapter.glob("*.trans.txt"))
    items = []
    for line in trans.read_text().splitlines():
        utt_id, _, text = line.partition(" ")
        audio = chapter / f"{utt_id}.flac"
        if audio.exists():
            items.append((audio, text.strip()))
    return items


def build_passage(utterances: list[tuple[Path, str]], seconds: float) -> list[tuple[Path, str]]:
    chosen, total = [], 0.0
    for audio, text in utterances:
        chosen.append((audio, text))
        total += duration_s(audio)
        if total >= seconds:
            return chosen
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LibriSpeech/test-clean directory")
    parser.add_argument("out", type=Path)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=180.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    made = 0
    for chapter in sorted(c for speaker in args.source.iterdir() for c in speaker.iterdir()):
        if made == args.count:
            break
        passage = build_passage(read_transcripts(chapter), args.seconds)
        if not passage:
            continue
        name = f"ls-{chapter.parent.name}-{chapter.name}"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
            listing.writelines(f"file '{a.resolve()}'\n" for a, _ in passage)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                listing.name,
                "-ac",
                "1",
                "-ar",
                "16000",
                str(args.out / f"{name}.wav"),
            ],
            check=True,
        )
        Path(listing.name).unlink()
        (args.out / f"{name}.txt").write_text(" ".join(t for _, t in passage).lower() + "\n")
        made += 1
        print(f"wrote {name}")
    print(f"{made} passages in {args.out}")


if __name__ == "__main__":
    main()
