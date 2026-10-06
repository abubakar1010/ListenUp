"""Spike #19 (B2): forced-alignment speed, memory and word boundaries for caption text.

Usage (one setting per run, so peak memory belongs to that setting):
    OMP_NUM_THREADS=2 spike-b2 data/passages --model MMS_FA --window-s 0 \\
        --out results/ --words-out results/words/
data/passages: NAME.<audio>, NAME.txt (the caption text) and NAME.json from
spike-passages. The passage's text is aligned to the passage's audio (the padding is
cut off first): creator captions are timed, so the product aligns the cues that cover
the passage, not text that is missing from the audio. Word times are written in the
file's time, like B1's, so the two can be compared (spike-compare).
"""

import argparse
import json
import os
import re
import resource
from pathlib import Path

from listenup_spikes.b1_transcribe import passages
from listenup_spikes.common import Report, measure

TARGET_CORE_S_PER_AUDIO_S = 0.2  # System Design 5.1
SAMPLE_RATE = 16000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--model", default="MMS_FA")
    parser.add_argument("--window-s", type=float, default=0.0, help="0: whole passage")
    parser.add_argument("--int8", action="store_true", help="dynamic int8 linear layers")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--words-out", type=Path)
    args = parser.parse_args()

    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    import torch  # after OMP_NUM_THREADS

    from listenup_spikes.align import Aligner
    from listenup_spikes.media import decode

    torch.set_num_threads(args.threads)
    with measure() as t_load:
        aligner = Aligner(args.model, args.window_s, args.int8)
    label = f"{args.model}-{'whole' if args.window_s <= 0 else f'w{args.window_s:g}s'}"
    label += "-int8" if args.int8 else ""
    report = Report(
        f"spike-19-b2-{label}",
        ["passage", "audio_s", "wall_s", "core_s_per_audio_s", "rtf", "words", "unaligned"],
    )
    rates = []
    for path, text in passages(args.data):
        meta = json.loads(path.with_suffix(".json").read_text())
        offset = float(meta["pad_before_s"])
        audio = decode(path)
        audio = audio[
            round(offset * SAMPLE_RATE) : round((offset + meta["passage_s"]) * SAMPLE_RATE)
        ]
        audio_s = len(audio) / SAMPLE_RATE
        try:
            with measure() as t:
                words = aligner.align(audio, text)
        except (RuntimeError, MemoryError) as error:  # out of memory is a result here
            report.add(
                passage=path.stem,
                set=meta["set"],
                audio_s=round(audio_s, 1),
                error=str(error)[:200],
            )
            continue
        rate = t.cpu_s / audio_s
        rates.append(rate)
        report.add(
            passage=path.stem,
            set=meta["set"],
            audio_s=round(audio_s, 1),
            wall_s=round(t.wall_s, 2),
            core_s_per_audio_s=round(rate, 3),
            rtf=round(t.wall_s / audio_s, 3),
            words=len(words),
            unaligned=sum(1 for w in text.split() if not re.search("[A-Za-z]", w)),
        )
        if args.words_out:
            out = args.words_out / label
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{path.stem}.json").write_text(
                json.dumps(
                    {
                        "source": f"{args.model} {label}",
                        "window": [offset, offset + audio_s],
                        "words": [
                            {"word": w.word, "start": w.start + offset, "end": w.end + offset}
                            for w in words
                        ],
                    }
                )
            )
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    report.summary.update(
        {
            "model": args.model,
            "emission": ("whole passage" if args.window_s <= 0 else f"{args.window_s:g} s windows")
            + (", int8" if args.int8 else ""),
            "threads": args.threads,
            "model load_s": round(t_load.wall_s, 1),
            "peak_rss_mb": round(rss_mb),
            "passages aligned": len(rates),
            "mean core-s/audio-s": round(sum(rates) / len(rates), 3) if rates else None,
            "max core-s/audio-s": round(max(rates), 3) if rates else None,
            "meets 0.2 target": bool(rates) and max(rates) <= TARGET_CORE_S_PER_AUDIO_S,
        }
    )
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
