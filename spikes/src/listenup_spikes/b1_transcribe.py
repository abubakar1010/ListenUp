"""Spike #18 (B1): CPU transcription speed and word accuracy with faster-whisper.

Usage (run once per setting; PYTHONPATH adds the product's Dictation rules):
    PYTHONPATH=../apps/api/src spike-b1 data/passages --model small.en --beam-size 5 \\
        --processes 2 --threads 2 --out results/ --words-out results/words/
data/passages: NAME.<audio>, NAME.txt (reference text) and, from spike-passages, NAME.json
(where the passage sits in the file). Without NAME.json the whole file is the passage.

As on the server (System Design 5.2), `--processes` worker processes run at once, each
with `--threads` threads (OMP_NUM_THREADS is set to match), and take passages from a
shared queue, so the speed includes contention for cores and memory bandwidth. Each
worker loads the model once (int8, silence skipped by the VAD, word timestamps on).
Audio is decoded by ffmpeg to 16 kHz float samples and handed to faster-whisper: its own
decoder fails with PyAV 19 (faster-whisper 1.2.1 passes an argument PyAV 19 removed), so
the product adapter decodes the same way. Core-seconds are each worker's CPU time across
its threads plus ffmpeg's, so decoding counts.
"""

import argparse
import json
import multiprocessing as mp
import os
import queue
import resource
import subprocess
import time
from pathlib import Path
from typing import Any

from listenup_spikes import product
from listenup_spikes.common import Report
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


def passage_window(audio: Path, audio_s: float) -> tuple[float, float]:
    """(start, end) of the passage inside the file, from NAME.json when present."""
    layout = audio.with_suffix(".json")
    if not layout.exists():
        return 0.0, audio_s
    meta = json.loads(layout.read_text())
    start = float(meta["pad_before_s"])
    return start, start + float(meta["passage_s"])


def trim_to_window(
    words: list[tuple[str, float, float]], start: float, end: float
) -> list[tuple[str, float, float]]:
    """Words whose midpoint falls inside the passage (the product cuts the same way)."""
    return [w for w in words if start <= (w[1] + w[2]) / 2 < end]


def _worker(
    model_name: str,
    beam_size: int,
    condition: bool,
    threads: int,
    tasks: "mp.Queue[str | None]",
    results: "mp.Queue[dict[str, Any]]",
) -> None:
    import numpy as np
    from faster_whisper import WhisperModel

    w0 = time.perf_counter()
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
    results.put({"kind": "loaded", "load_s": time.perf_counter() - w0})
    while (path := tasks.get()) is not None:
        w0, c0 = time.perf_counter(), time.process_time()
        ch0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        pcm = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", path]
            + ["-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True,
            check=True,
        ).stdout
        audio = np.frombuffer(pcm, dtype=np.float32)
        segments, info = model.transcribe(
            audio,
            language="en",
            beam_size=beam_size,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=condition,
        )
        words = [
            (w.word.strip(), float(w.start), float(w.end))
            for s in segments  # the generator does the work
            for w in (s.words or [])
            if w.word.strip()
        ]
        ch1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = (ch1.ru_utime + ch1.ru_stime) - (ch0.ru_utime + ch0.ru_stime)
        results.put(
            {
                "kind": "passage",
                "path": path,
                "audio_s": float(info.duration),
                "wall_s": time.perf_counter() - w0,
                "cpu_s": time.process_time() - c0 + child_cpu,
                "words": words,
            }
        )
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB
    results.put({"kind": "done", "peak_rss_mb": rss_mb})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument(
        "--no-condition",
        action="store_true",
        help="condition_on_previous_text=False (distil-whisper's model card asks for it)",
    )
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--processes", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--words-out", type=Path, help="write each transcript's words here")
    args = parser.parse_args()

    if not product.available():
        raise SystemExit("set PYTHONPATH=../apps/api/src: the Dictation rules are needed")
    items = passages(args.data)
    reference_of = {str(path): text for path, text in items}
    label = f"{args.model}-beam{args.beam_size}" + ("-nocond" if args.no_condition else "")

    os.environ["OMP_NUM_THREADS"] = str(args.threads)  # inherited by the workers
    ctx = mp.get_context("spawn")
    tasks: mp.Queue[str | None] = ctx.Queue()
    results: mp.Queue[dict[str, Any]] = ctx.Queue()
    for path, _ in items:
        tasks.put(str(path))
    for _ in range(args.processes):
        tasks.put(None)
    w0 = time.perf_counter()
    workers = [
        ctx.Process(
            target=_worker,
            args=(
                args.model,
                args.beam_size,
                not args.no_condition,
                args.threads,
                tasks,
                results,
            ),
        )
        for _ in range(args.processes)
    ]
    for w in workers:
        w.start()

    report = Report(
        f"spike-18-b1-{label}",
        [
            "passage",
            "audio_s",
            "wall_s",
            "core_s_per_audio_s",
            "rtf",
            "wer",
            "dictation_wer",
            "subs",
            "dels",
            "ins",
            "false_marks",
            "perfect_learner_accuracy",
        ],
    )
    load_s, rss, done = [], [], 0
    while done < args.processes:
        try:
            msg = results.get(timeout=30)
        except queue.Empty:
            if any(w.exitcode not in (None, 0) for w in workers):
                raise SystemExit("a worker process failed; see its error above") from None
            continue
        if msg["kind"] == "loaded":
            load_s.append(msg["load_s"])
            continue
        if msg["kind"] == "done":
            rss.append(msg["peak_rss_mb"])
            done += 1
            continue
        path = Path(msg["path"])
        start, end = passage_window(path, msg["audio_s"])
        words = trim_to_window([tuple(w) for w in msg["words"]], start, end)
        text = " ".join(w[0] for w in words)
        reference = reference_of[msg["path"]]
        plain = word_error_rate(reference, text)
        dictation = product.dictation_wer(reference, text)
        marks = product.false_marks(words, reference)
        report.add(
            passage=path.stem,
            set=json.loads(path.with_suffix(".json").read_text())["set"]
            if path.with_suffix(".json").exists()
            else "",
            audio_s=round(msg["audio_s"], 1),
            passage_s=round(end - start, 1),
            wall_s=round(msg["wall_s"], 1),
            core_s_per_audio_s=round(msg["cpu_s"] / msg["audio_s"], 3),
            rtf=round(msg["wall_s"] / msg["audio_s"], 3),
            wer=round(plain.wer, 4),
            dictation_wer=round(dictation.wer, 4),
            subs=dictation.substitutions,
            dels=dictation.deletions,
            ins=dictation.insertions,
            reference_words=dictation.reference_words,
            false_marks=marks.marks,
            perfect_learner_accuracy=marks.accuracy,
        )
        if args.words_out:
            out = args.words_out / label
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{path.stem}.json").write_text(
                json.dumps(
                    {
                        "source": f"faster-whisper {label}",
                        "window": [start, end],
                        "words": [{"word": w, "start": s, "end": e} for w, s, e in msg["words"]],
                    }
                )
            )
    for w in workers:
        w.join()
    total_wall = time.perf_counter() - w0

    rows = report.rows
    rates = [r["core_s_per_audio_s"] for r in rows]
    audio_total = sum(r["audio_s"] for r in rows)
    ref_words = sum(r["reference_words"] for r in rows)
    errors = sum(r["subs"] + r["dels"] + r["ins"] for r in rows)
    report.summary.update(
        {
            "model": args.model,
            "beam_size": args.beam_size,
            "condition_on_previous_text": not args.no_condition,
            "layout": f"{args.processes} processes x {args.threads} threads",
            "passages": len(rows),
            "audio_s total": round(audio_total, 1),
            "wall_s total": round(total_wall, 1),
            "throughput audio-s per wall-s": round(audio_total / total_wall, 2),
            "load_s mean": round(sum(load_s) / len(load_s), 1),
            "peak_rss_mb per process": round(max(rss)),
            "mean core-s/audio-s": round(sum(rates) / len(rates), 3),
            "p95 core-s/audio-s": round(percentile(rates, 95), 3),
            "pooled dictation WER": round(errors / ref_words, 4),
            "mean dictation WER": round(sum(r["dictation_wer"] for r in rows) / len(rows), 4),
            "mean plain WER": round(sum(r["wer"] for r in rows) / len(rows), 4),
            "false marks per 100 words": round(
                100 * sum(r["false_marks"] for r in rows) / ref_words, 2
            ),
            "meets speed target": percentile(rates, 95) <= TARGET_CORE_S_PER_AUDIO_S,
        }
    )
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
