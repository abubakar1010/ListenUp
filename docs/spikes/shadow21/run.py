"""B3: full prototype round against a precomputed reference, warm, no queue."""

import argparse
import hashlib
import importlib.metadata
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shadow20"))
import experiment as e
import numpy as np
import pyarrow.parquet as pq
import torch
from core import pack, summary, validate_budget, windows
from faster_whisper.vad import VadOptions, get_speech_timestamps
from inference import Windowed


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False))


def prepare(data, out):
    corpora = {
        speaker: {
            r["file"].split("-", 1)[1]: r
            for r in pq.read_table(data / f"{speaker}.parquet").to_pylist()
        }
        for speaker in ["bdl", "slt", "clb"]
    }
    names = sorted(set.intersection(*(set(c) for c in corpora.values())))
    records = []
    # Ten passages for each speaker. Different speakers supply the references.
    for speaker, reference in [("bdl", "slt"), ("slt", "clb"), ("clb", "bdl")]:
        items = [
            (name, len(e.read_bytes(corpora[speaker][name]["audio"]["bytes"])) / e.RATE)
            for name in names
        ]
        for group in pack(items, count=10):
            candidates, references, texts = [], [], []
            for name, _ in group:
                row, ref = corpora[speaker][name], corpora[reference][name]
                if row["text"] != ref["text"]:
                    raise ValueError("Reference text mismatch")
                candidates.append(e.read_bytes(row["audio"]["bytes"]))
                references.append(e.read_bytes(ref["audio"]["bytes"]))
                texts.append(row["text"])
            audio, original = np.concatenate(candidates), np.concatenate(references)
            ident = f"{speaker}-{len(records) + 1:02d}"
            # Scratch WAVs exercise the same decode boundary as a stored recording.
            for kind, samples in [("round", audio), ("reference", original)]:
                e.sf.write(
                    data / f"{ident}-{kind}.wav", samples, e.RATE, subtype="PCM_16"
                )
            records.append(
                {
                    "id": ident,
                    "speaker": speaker,
                    "reference_speaker": reference,
                    "sources": [name for name, _ in group],
                    "text": " ".join(texts),
                    "duration_s": len(audio) / e.RATE,
                    "reference_duration_s": len(original) / e.RATE,
                    "waveform_sha256": hashlib.sha256(audio.tobytes()).hexdigest(),
                }
            )
    write(out / "manifest.json", records)
    return records


def set_spans(models, audio):
    speech = get_speech_timestamps(audio, VadOptions(speech_pad_ms=400))
    spans = windows(speech, e.RATE)
    models.word.spans = models.phone.spans = spans
    return spans


def load(path):
    # Include real ffmpeg decode in each candidate's timer (75 s PCM input).
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-threads",
            "2",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-threads",
            "2",
            "-",
        ]
    )
    return np.frombuffer(raw, dtype=np.float32).copy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    cgroup = {
        p: Path("/sys/fs/cgroup", p).read_text().strip()
        for p in ["cpu.max", "memory.max", "memory.swap.max"]
    }
    validate_budget(
        cgroup["cpu.max"],
        cgroup["memory.max"],
        cgroup["memory.swap.max"],
        torch.get_num_threads(),
        torch.get_num_interop_threads(),
    )
    records = prepare(args.data, args.out)
    models = e.Models(args.data)
    models.word = torch.ao.quantization.quantize_dynamic(
        models.word, {torch.nn.Linear}, dtype=torch.qint8
    )
    models.word = Windowed(models.word, phone=False)
    models.word.labels = len(models.labels)
    models.phone = Windowed(models.phone, phone=True)
    models.phone.labels = len(models.vocab)

    # VAD inside recognize, all other #20 options unchanged; one ASR worker.
    def recognize(audio):
        segments, _ = models.asr.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt="Um, uh, er, erm, like, you know.",
            word_timestamps=False,
        )
        return " ".join(s.text for s in segments).strip()

    models.recognize = recognize
    write(
        args.out / "settings.json",
        {
            "label": "CI-runner evidence (E4)",
            "torch_threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "quantized_engine": torch.backends.quantized.engine,
            "window_s": 30,
            "phone_precision": "fp32",
            "word_precision": "dynamic int8",
            "whisper": "small.en int8 beam5",
            "vad": "Silero defaults, 400 ms padding for acoustic passes; Whisper default padding",
            "memory_bytes": 8589934592,
            "cpu_quota": 2,
            "queue": False,
            "packages": {
                p: importlib.metadata.version(p)
                for p in [
                    "torch",
                    "torchaudio",
                    "faster-whisper",
                    "ctranslate2",
                    "transformers",
                    "praat-parselmouth",
                ]
            },
            "cgroup": {
                p: Path("/sys/fs/cgroup", p).read_text().strip()
                for p in ["cpu.max", "memory.max", "memory.swap.max"]
            },
        },
    )
    references = {}
    for row in records:
        original = load(args.data / f"{row['id']}-reference.wav")
        set_spans(models, original)
        aligned = models.word_align(original, row["text"])
        ref = {
            "aligned": aligned,
            "phones": models.phone_profile(original, row["text"]),
            "pitch": e.pitch(original, aligned),
            "transcript": models.recognize(original),
        }
        references[row["id"]] = original, ref
        print("reference ready", row["id"], flush=True)
    # Full candidate warmup: models, VAD, decoders and transforms. Not sampled.
    first = records[0]
    audio = load(args.data / f"{first['id']}-round.wav")
    set_spans(models, audio)
    original, ref = references[first["id"]]
    e.assess(models, original, audio, first["text"], ref)
    results = []
    for row in records:
        original, ref = references[row["id"]]
        start = time.perf_counter()
        audio = load(args.data / f"{row['id']}-round.wav")
        spans = set_spans(models, audio)
        assessment = e.assess(models, original, audio, row["text"], ref)
        elapsed = time.perf_counter() - start
        results.append(
            {
                "id": row["id"],
                "latency_s": elapsed,
                "acoustic_windows": len(spans),
                "speech_processed_s": sum(b - a for a, b in spans) / e.RATE,
                "assessment": assessment,
            }
        )
        write(args.out / "recordings.json", results)
        print("analysed", row["id"], round(elapsed, 3), flush=True)
    report = summary([r["latency_s"] for r in results])
    report["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(args.out / "summary.json", report)
    write(
        args.out / "input-hashes.json",
        json.loads((args.data / "input-hashes.json").read_text()),
    )
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
