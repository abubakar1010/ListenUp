"""CPU-only research harness. See README for fetch/run; no learner data or API imports."""

import argparse
import hashlib
import io
import itertools
import json
import os
import re
import subprocess
from pathlib import Path

import espeakng_loader
import numpy as np
import parselmouth
import pyarrow.parquet as pq
import soundfile as sf
import torch
import torchaudio
from faster_whisper import WhisperModel
from measures import echo, filler_count, fluency, gop, matched_indices, relative, timing
from phonemizer import phonemize
from phonemizer.backend.espeak.wrapper import EspeakWrapper
from phonemizer.separator import Separator
from scipy.signal import butter, sosfiltfilt
from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

RATE = 16000
NAMES = [
    "timing",
    "pronunciation",
    "accent",
    "articulation",
    "fluency",
    "fillers",
    "completeness",
]


def words(text):
    # Same whitespace-word convention as ADR 0034; selected ARCTIC text is ASCII.
    return [
        re.sub("[^a-z']", "", w.lower()).strip("'")
        for w in text.split()
        if re.search("[a-zA-Z]", w)
    ]


def read_bytes(blob):
    audio, rate = sf.read(io.BytesIO(blob), dtype="float32")
    assert rate == RATE and audio.ndim == 1
    return audio


def forced(logp, ids):
    labels, scores = torchaudio.functional.forced_align(
        logp[None], torch.tensor([ids], dtype=torch.int32), blank=0
    )
    spans = torchaudio.functional.merge_tokens(labels[0], scores[0].exp(), blank=0)
    assert len(spans) == len(ids)
    return spans


class Models:
    def __init__(self, data):
        torch.hub.set_dir(str(data / "torch"))
        checkpoint = (
            data / "torch/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth"
        )
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        if not checkpoint.exists():
            checkpoint.symlink_to((data / "word.pth").resolve())
        self.word = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_model()
        self.word.eval()
        self.labels = {
            c: i
            for i, c in enumerate(
                torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_labels()
            )
        }
        self.phone = Wav2Vec2ForCTC.from_pretrained(
            data / "phone", local_files_only=True
        ).eval()
        self.feature = Wav2Vec2FeatureExtractor.from_pretrained(
            data / "phone", local_files_only=True
        )
        self.vocab = json.loads((data / "phone/vocab.json").read_text())
        self.phone_ids = [v for k, v in self.vocab.items() if not k.startswith("<")]
        self.asr = WhisperModel(
            str(data / "whisper"), device="cpu", compute_type="int8", cpu_threads=2
        )
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        os.environ["ESPEAK_DATA_PATH"] = str(espeakng_loader.get_data_path())

    def word_align(self, audio, text):
        tokens = words(text)
        ids, lengths = [], []
        for i, w in enumerate(tokens):
            if i:
                ids.append(self.labels["|"])
            ids.extend(self.labels[c] for c in w.upper())
            lengths.append(len(w))
        with torch.inference_mode():
            emissions, _ = self.word(torch.from_numpy(audio)[None])
            logp = emissions[0].log_softmax(-1)
        spans = [s for s in forced(logp, ids) if s.token != self.labels["|"]]
        out, offset = [], 0
        for w, n in zip(tokens, lengths):
            ss = spans[offset : offset + n]
            offset += n
            out.append(
                {"word": w, "start": ss[0].start * 0.02, "end": ss[-1].end * 0.02}
            )
        return out

    def phone_profile(self, audio, text):
        pronunciations = phonemize(
            words(text),
            language="en-us",
            backend="espeak",
            separator=Separator(phone=" ", word="|", syllable=""),
            strip=True,
        )
        seqs = [p.replace("|", " ").split() for p in pronunciations]
        unknown = sorted({p for ps in seqs for p in ps if p not in self.vocab})
        if unknown:
            raise ValueError(f"Unsupported phones: {unknown}")
        ids = [self.vocab[p] for ps in seqs for p in ps]
        inputs = self.feature(audio, sampling_rate=RATE, return_tensors="pt")
        with torch.inference_mode():
            lp = self.phone(**inputs).logits[0].log_softmax(-1)
        spans = forced(lp, ids)
        raw = lp.numpy()
        values = [
            gop(raw[s.start : s.end], int(s.token), self.phone_ids) for s in spans
        ]
        out, offset = [], 0
        for ps in seqs:
            vs = values[offset : offset + len(ps)]
            offset += len(ps)
            out.append(
                {"phones": ps, "gop": vs, "mean": float(np.mean(vs)), "ending": vs[-1]}
            )
        return out

    def recognize(self, audio):
        segments, _ = self.asr.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt="Um, uh, er, erm, like, you know.",
            word_timestamps=False,
        )
        return " ".join(s.text for s in segments).strip()


def pitch(audio, aligned):
    track = parselmouth.Sound(audio, sampling_frequency=RATE).to_pitch(
        time_step=0.01, pitch_floor=60, pitch_ceiling=500
    )
    hz = track.selected_array["frequency"]
    times = track.xs()
    out = []
    for w in aligned:
        voiced = hz[(times >= w["start"]) & (times < w["end"]) & (hz > 0)]
        out.append(float(12 * np.log2(np.median(voiced))) if len(voiced) else None)
    return out


def assess(models, original, audio, text, ref):
    aligned = models.word_align(audio, text)
    phones = models.phone_profile(audio, text)
    transcript = models.recognize(audio)
    matches = matched_indices(words(text), words(transcript))
    present = {i for i, _ in matches}
    p = pitch(audio, aligned)
    valid = [i for i in present if p[i] is not None and ref["pitch"][i] is not None]
    accent = None
    if len(valid) >= 4:
        x = np.array([ref["pitch"][i] for i in valid])
        y = np.array([p[i] for i in valid])
        if x.std() > 0.01 and y.std() > 0.01:
            accent = float(100 * max(0, np.corrcoef(x, y)[0, 1]))
    idx = sorted(present)
    onsets = lambda a: [a[i]["start"] for i in idx]
    gaps = lambda a: np.array(
        [a[j]["start"] - a[i]["end"] for i, j in itertools.pairwise(idx)]
    )
    pron = relative(
        np.mean([x["mean"] for x in phones]),
        np.mean([x["mean"] for x in ref["phones"]]),
    )
    articulation = relative(
        np.mean([x["ending"] for x in phones]),
        np.mean([x["ending"] for x in ref["phones"]]),
    )
    fc = filler_count(transcript)
    base = filler_count(ref["transcript"])
    # All scores relative to the original; no fixed native-speaker target.
    excess = max(0, fc / (len(audio) / RATE) - base / (len(original) / RATE)) * 60
    scores = {
        "timing": timing(onsets(ref["aligned"]), onsets(aligned)),
        "pronunciation": pron,
        "accent": accent,
        "articulation": articulation,
        "fluency": fluency(gaps(ref["aligned"]), gaps(aligned)),
        "fillers": max(0, 100 - 100 * excess / 6),
        "completeness": 100 * len(matches) / len(aligned),
    }
    return {
        "scores": scores,
        "transcript": transcript,
        "filler_count": fc,
        "matched_words": len(matches),
        "total_words": len(aligned),
        "words": aligned,
        "phones": phones,
        "pitch": p,
        "markers": [
            "missed"
            if i not in present
            else "good"
            if relative(x["mean"], ref["phones"][i]["mean"]) >= 70
            else "needs work"
            for i, x in enumerate(phones)
        ],
        "echo": echo(original, audio),
    }


def build(data, models):
    corpora = {
        s: {
            r["file"].split("-", 1)[1]: r
            for r in pq.read_table(data / f"{s}.parquet").to_pylist()
        }
        for s in ["bdl", "slt", "clb"]
    }
    ids = [
        k
        for k in sorted(set.intersection(*(set(c) for c in corpora.values())))
        if all(len(words(c[k]["text"])) >= 8 for c in corpora.values())
    ][:10]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "flite=text=um uh:voice=slt",
            "-ar",
            str(RATE),
            str(data / "filler.wav"),
        ],
        check=True,
    )
    filler, _ = sf.read(data / "filler.wav", dtype="float32")
    manifest = []
    for n, k in enumerate(ids):
        s, t = ["bdl", "slt", "clb"][n % 3], ["slt", "clb", "bdl"][n % 3]
        a, b = corpora[s][k], corpora[t][k]
        assert a["text"] == b["text"]
        original, good = (
            read_bytes(a["audio"]["bytes"]),
            read_bytes(b["audio"]["bytes"]),
        )
        aligned = models.word_align(good, a["text"])
        mid = len(aligned) // 2
        cut0, cut1 = (
            round(aligned[mid]["start"] * RATE),
            round(aligned[mid]["end"] * RATE),
        )
        skipped = np.r_[good[:cut0], good[cut1:]]
        low = sosfiltfilt(butter(6, 900, fs=RATE, output="sos"), skipped).astype(
            "float32"
        )
        poor = np.r_[
            np.zeros(round(1.2 * RATE)),
            low[:cut0],
            np.zeros(round(0.6 * RATE)),
            filler,
            low[cut0:],
        ].astype("float32")
        folder = data / "pairs" / f"{n + 1:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        recordings = {"original": original, "good": good, "poor": poor}
        if n < 2:
            recordings.update(
                late=np.r_[np.zeros(round(1.2 * RATE)), good],
                lowpass=sosfiltfilt(butter(6, 900, fs=RATE, output="sos"), good),
                skip=skipped,
                fill=np.r_[good[:cut0], filler, good[cut0:]],
            )
        hashes = {}
        for name, x in recordings.items():
            path = folder / f"{name}.wav"
            sf.write(path, x, RATE, subtype="PCM_16")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        row = {
            "pair": f"{n + 1:02d}",
            "prompt": k,
            "text": a["text"],
            "original_speaker": s,
            "good_speaker": t,
            "skipped_word": aligned[mid]["word"],
            "skip_interval_s": [cut0 / RATE, cut1 / RATE],
            "inserted_fillers": 2,
            "poor_synthetic": True,
            "hashes": hashes,
        }
        manifest.append(row)
    (data / "manifest.json").write_text(json.dumps(manifest, indent=2))


def run(data, out, models):
    manifest = json.loads((data / "manifest.json").read_text())
    results = []
    for row in manifest:
        folder = data / "pairs" / row["pair"]
        original, _ = sf.read(folder / "original.wav", dtype="float32")
        aligned = models.word_align(original, row["text"])
        ref = {
            "aligned": aligned,
            "phones": models.phone_profile(original, row["text"]),
            "pitch": pitch(original, aligned),
            "transcript": models.recognize(original),
        }
        recs = {}
        for path in sorted(folder.glob("*.wav")):
            if path.stem == "original":
                continue
            audio, _ = sf.read(path, dtype="float32")
            recs[path.stem] = assess(models, original, audio, row["text"], ref)
        good, _ = sf.read(folder / "good.wav", dtype="float32")
        # Exact copy, and a 0.8-amplitude digital leak into an independent voice.
        m = max(len(original), len(good))
        pad = lambda x, size=m: np.pad(x, (0, size - len(x)))
        leak = echo(original, pad(good) + 0.8 * pad(original))
        results.append(
            dict(
                **row,
                reference=ref,
                recordings=recs,
                echo_controls={
                    "copy": echo(original, original),
                    "mixed": leak,
                    "clean": recs["good"]["echo"],
                },
            )
        )
        print("completed", row["pair"], flush=True)
        out.write_text(json.dumps(results, indent=2, allow_nan=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "run"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--phone-int8", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(2)
    models = Models(args.data)
    if args.phone_int8:
        models.phone = torch.ao.quantization.quantize_dynamic(
            models.phone, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
        )
    # ADR 0034's provisional word-aligner choice. Short clips fit a single window.
    models.word = torch.ao.quantization.quantize_dynamic(
        models.word, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
    )
    if args.action == "build":
        build(args.data, models)
    else:
        run(args.data, args.out, models)


if __name__ == "__main__":
    main()
