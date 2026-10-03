"""Spike #20 (measures) and #21 (B3 latency): analyse Shadow recordings against the original.

Usage:
    OMP_NUM_THREADS=2 spike-shadow data/shadow --out results/ [--fillers-model small.en]
data/shadow/<pair>/: original.<audio>, original.txt (the segment text), and one or more
learner recordings, e.g. good.<audio> and poor.<audio> (deliberately mumbled and late).
The original's reference profile is computed once per pair; only learner audio is timed,
which is what B3 measures (scores under 50 s at p95).
"""

import argparse
from pathlib import Path

from listenup_spikes.align import Aligner
from listenup_spikes.b1_transcribe import AUDIO_SUFFIXES
from listenup_spikes.common import Report, measure
from listenup_spikes.media import decode
from listenup_spikes.metrics import count_fillers, percentile
from listenup_spikes.shadow_measures import (
    ECHO_THRESHOLD,
    MEASURES,
    RoundMeasures,
    accent,
    articulation,
    completeness,
    echo_score,
    fillers_score,
    fluency,
    pronunciation,
    timing,
    word_pitch,
)

B3_BUDGET_S = 50.0
FRAME_S = 0.01


def pitch_track(audio):  # type: ignore[no-untyped-def]
    import parselmouth

    pitch = parselmouth.Sound(audio, sampling_frequency=16000).to_pitch(time_step=FRAME_S)
    return pitch.selected_array["frequency"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument(
        "--fillers-model",
        default=None,
        help="faster-whisper model for the filler pass (omit to skip)",
    )
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()

    aligner = Aligner()
    whisper = None
    if args.fillers_model:
        from faster_whisper import WhisperModel

        from listenup_spikes.b4_fillers import SETTINGS

        whisper = WhisperModel(args.fillers_model, device="cpu", compute_type="int8", cpu_threads=2)
    report = Report(
        "spike-20-21-shadow", ["pair", "recording", "analysis_s", *MEASURES, "overall", "echo"]
    )
    timings: list[float] = []
    wins = {m: 0 for m in (*MEASURES, "overall")}
    pairs_compared = 0
    for pair in sorted(p for p in args.data.iterdir() if p.is_dir()):
        original_path = next(
            p for p in pair.iterdir() if p.stem == "original" and p.suffix.lower() in AUDIO_SUFFIXES
        )
        text = (pair / "original.txt").read_text()
        original_audio = decode(original_path)
        with measure() as t_profile:
            original_words = aligner.align(original_audio, text)
            original_pitch = word_pitch(pitch_track(original_audio), FRAME_S, original_words)
        report.summary[f"{pair.name} profile_s"] = round(t_profile.wall_s, 1)
        results = {}
        for rec in sorted(
            p for p in pair.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES and p.stem != "original"
        ):
            with measure() as t:
                audio = decode(rec)
                words = aligner.align(audio, text)
                learner_pitch = word_pitch(pitch_track(audio), FRAME_S, words)
                filler_count = None
                if whisper is not None:
                    segments, _ = whisper.transcribe(
                        audio, language="en", initial_prompt=SETTINGS["disfluent-prompt"]
                    )
                    filler_count = count_fillers(" ".join(s.text for s in segments))
                scores = {
                    "timing": timing(original_words, words),
                    "pronunciation": pronunciation(words),
                    "accent": accent(original_pitch, learner_pitch),
                    "articulation": articulation(words),
                    "fluency": fluency(original_words, words),
                    "fillers": fillers_score(filler_count, len(audio) / 16000),
                    "completeness": completeness(words),
                }
                round_measures = RoundMeasures(scores)
                echo = echo_score(original_audio, audio)
            timings.append(t.wall_s)
            results[rec.stem] = round_measures
            report.add(
                pair=pair.name,
                recording=rec.stem,
                analysis_s=round(t.wall_s, 1),
                **{k: None if v is None else round(v, 1) for k, v in scores.items()},
                overall=round(round_measures.overall, 1),
                echo=f"{echo:.2f}{' LEAK' if echo >= ECHO_THRESHOLD else ''}",
            )
        if "good" in results and "poor" in results:
            pairs_compared += 1
            good, poor = results["good"], results["poor"]
            for m in MEASURES:
                g, p = good.scores.get(m), poor.scores.get(m)
                if g is not None and p is not None and g > p:
                    wins[m] += 1
            wins["overall"] += good.overall > poor.overall
    if pairs_compared:
        report.summary |= {
            f"good beats poor: {m}": f"{n}/{pairs_compared}" for m, n in wins.items()
        }
    if timings:
        p95 = percentile(timings, 95)
        report.summary |= {
            "recordings": len(timings),
            "p50 analysis_s": percentile(timings, 50),
            "p95 analysis_s": p95,
            "B3 budget_s": B3_BUDGET_S,
            "B3 pass": p95 <= B3_BUDGET_S,
        }
    print(f"wrote {report.write(args.out)}")


if __name__ == "__main__":
    main()
