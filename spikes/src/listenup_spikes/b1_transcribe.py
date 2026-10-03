"""Spike #18 (B1): CPU transcription speed and word accuracy with faster-whisper.

Usage (on the stage 0 server):
    OMP_NUM_THREADS=2 spike-b1 data/passages --models tiny.en base.en small.en --out results/
data/passages: pairs NAME.<audio> and NAME.txt (hand-checked reference text), 3-minute passages.
"""

import argparse
from pathlib import Path

from listenup_spikes.common import Report, measure
from listenup_spikes.media import decode
from listenup_spikes.metrics import percentile, word_error_rate

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".webm"}
TARGET_CORE_S_PER_AUDIO_S = 1.0  # System Design 2.2


def passages(data: Path) -> list[tuple[Path, str]]:
    found = []
    for audio in sorted(p for p in data.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES):
        ref = audio.with_suffix(".txt")
        if ref.exists():
            found.append((audio, ref.read_text()))
    if not found:
        raise SystemExit(f"no audio + .txt pairs in {data}")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--models", nargs="+", default=["tiny.en", "base.en", "small.en"])
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    items = passages(args.data)
    report = Report(
        "spike-18-b1-transcription",
        [
            "model",
            "passage",
            "audio_s",
            "wall_s",
            "core_s_per_audio_s",
            "wer",
            "subs",
            "dels",
            "ins",
        ],
    )
    for name in args.models:
        with measure() as t_load:
            model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=args.threads)
        report.summary[f"{name} load_s"] = round(t_load.wall_s, 1)
        rates, wers = [], []
        for path, reference in items:
            audio = decode(path)
            audio_s = len(audio) / 16000
            with measure() as t:
                segments, _ = model.transcribe(
                    audio,
                    language="en",
                    beam_size=args.beam_size,
                    vad_filter=True,
                    word_timestamps=True,
                )
                text = " ".join(seg.text for seg in segments)  # the generator does the work
            result = word_error_rate(reference, text)
            rate = t.cpu_s / audio_s
            rates.append(rate)
            wers.append(result.wer)
            report.add(
                model=name,
                passage=path.stem,
                audio_s=round(audio_s, 1),
                wall_s=round(t.wall_s, 1),
                core_s_per_audio_s=round(rate, 3),
                wer=round(result.wer, 4),
                subs=result.substitutions,
                dels=result.deletions,
                ins=result.insertions,
            )
        report.summary[f"{name} mean core-s/audio-s"] = round(sum(rates) / len(rates), 3)
        report.summary[f"{name} p95 core-s/audio-s"] = round(percentile(rates, 95), 3)
        report.summary[f"{name} mean WER"] = round(sum(wers) / len(wers), 4)
        report.summary[f"{name} meets speed target"] = (
            percentile(rates, 95) <= TARGET_CORE_S_PER_AUDIO_S
        )
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
