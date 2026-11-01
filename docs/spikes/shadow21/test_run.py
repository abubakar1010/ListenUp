"""Deterministic orchestration checks; external speech/download boundaries are fake.

Added after orchestration implementation: characterization, not test-first evidence.
"""

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


def load_runner(experiment):
    vad = types.ModuleType("faster_whisper.vad")
    vad.VadOptions = object
    vad.get_speech_timestamps = lambda *args: []
    pq = types.ModuleType("pyarrow.parquet")
    pyarrow = types.ModuleType("pyarrow")
    pyarrow.parquet = pq
    spec = importlib.util.spec_from_file_location(
        "b3_run", Path(__file__).with_name("run.py")
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "experiment": experiment,
            "pyarrow": pyarrow,
            "pyarrow.parquet": pq,
            "faster_whisper.vad": vad,
        },
    ):
        spec.loader.exec_module(module)
    return module


class OrchestrationTests(unittest.TestCase):
    def test_reference_precompute_and_warmup_precede_all_30_timers(self):
        events = []
        rows = [{"id": str(i), "text": "a"} for i in range(30)]

        class Models:
            def __init__(self, data):
                self.word = self.phone = object()
                self.labels = self.vocab = [0, 1, 2]
                self.asr = types.SimpleNamespace(transcribe=lambda *a, **kw: ([], None))

            def word_align(self, audio, text):
                events.append("reference")
                return []

            def phone_profile(self, audio, text):
                return []

        experiment = types.ModuleType("experiment")
        experiment.Models = Models
        experiment.RATE = 16000
        experiment.pitch = lambda *args: []

        def assess(*args):
            events.append("assess")
            return {"scores": {}}

        experiment.assess = assess
        module = load_runner(experiment)
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            if str(path).startswith("/sys/fs/cgroup/"):
                return {
                    "cpu.max": "200000 100000",
                    "memory.max": "8589934592",
                    "memory.swap.max": "0",
                }[path.name]
            return original_read(path, *args, **kwargs)

        ticks = iter(range(60))

        def clock():
            events.append("clock")
            return next(ticks)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "input-hashes.json").write_text("{}")
            with (
                patch.object(
                    sys, "argv", ["run.py", "--data", folder, "--out", folder]
                ),
                patch.object(module, "prepare", return_value=rows),
                patch.object(
                    module, "load", return_value=np.zeros(16000, dtype=np.float32)
                ),
                patch.object(module, "set_spans", return_value=[(0, 16000)]),
                patch.object(module.torch, "set_num_threads"),
                patch.object(module.torch, "set_num_interop_threads"),
                patch.object(module.torch, "get_num_threads", return_value=2),
                patch.object(module.torch, "get_num_interop_threads", return_value=2),
                patch.object(
                    module.torch.ao.quantization,
                    "quantize_dynamic",
                    side_effect=lambda m, *a, **k: m,
                ),
                patch.object(module.importlib.metadata, "version", return_value="test"),
                patch.object(Path, "read_text", read),
                patch.object(module.time, "perf_counter", side_effect=clock),
                patch("builtins.print"),
            ):
                module.main()
            self.assertEqual(events[:31], ["reference"] * 30 + ["assess"])
            self.assertEqual(events[31:], ["clock", "assess", "clock"] * 30)
            result = json.loads((root / "summary.json").read_text())
            self.assertEqual(result["count"], 30)
            self.assertEqual(result["p50_s"], 1)
            self.assertEqual(result["p95_s"], 1)
            self.assertEqual(
                len(json.loads((root / "recordings.json").read_text())), 30
            )


class WorkloadTests(unittest.TestCase):
    def test_manifest_has_30_whole_75_second_rounds_and_checks_reference_text(self):
        experiment = types.ModuleType("experiment")
        experiment.RATE = 1
        experiment.read_bytes = lambda blob: np.ones(25, dtype=np.float32)
        written = []
        experiment.sf = types.SimpleNamespace(
            write=lambda path, samples, *a, **kw: written.append(len(samples))
        )
        module = load_runner(experiment)

        def table(path):
            speaker = path.stem
            return types.SimpleNamespace(
                to_pylist=lambda: [
                    {
                        "file": f"{speaker}-{i:04d}.wav",
                        "text": "the same words",
                        "audio": {"bytes": b"public-input-fake"},
                    }
                    for i in range(40)
                ]
            )

        module.pq.read_table = table
        with tempfile.TemporaryDirectory() as folder:
            records = module.prepare(Path(folder), Path(folder))
            self.assertEqual(len(records), 30)
            self.assertEqual(written, [75] * 60)
            self.assertTrue(all(r["duration_s"] == 75 for r in records))
            self.assertEqual(
                records[0]["sources"], ["0000.wav", "0001.wav", "0002.wav"]
            )
            self.assertEqual(records[0]["reference_speaker"], "slt")
            self.assertEqual(records[-1]["id"], "clb-30")
            for speaker in ["bdl", "slt", "clb"]:
                sources = [
                    name
                    for r in records
                    if r["speaker"] == speaker
                    for name in r["sources"]
                ]
                self.assertEqual(len(sources), len(set(sources)))
            good_table = table

            def mismatched(path):
                rows = good_table(path).to_pylist()
                if path.stem == "slt":
                    rows[0]["text"] = "different words"
                return types.SimpleNamespace(to_pylist=lambda: rows)

            module.pq.read_table = mismatched
            with self.assertRaisesRegex(ValueError, "Reference text mismatch"):
                module.prepare(Path(folder), Path(folder))

    def test_decode_requests_mono_16khz_and_preserves_pcm(self):
        module = load_runner(types.ModuleType("experiment"))
        with patch.object(
            module.subprocess,
            "check_output",
            return_value=np.array([0.25, -0.5], dtype=np.float32).tobytes(),
        ) as decode:
            audio = module.load(Path("candidate.wav"))
        self.assertEqual(audio.tolist(), [0.25, -0.5])
        args = decode.call_args.args[0]
        self.assertEqual(args[args.index("-ar") + 1], "16000")
        self.assertEqual(args[args.index("-ac") + 1], "1")
        self.assertIn("candidate.wav", args)

    def test_vad_drives_both_models_without_compressing_the_recording_clock(self):
        experiment = types.ModuleType("experiment")
        experiment.RATE = 16000
        module = load_runner(experiment)
        module.VadOptions = lambda **kw: kw
        module.get_speech_timestamps = lambda audio, options: [
            {"start": 16000, "end": 1040000}
        ]
        models = types.SimpleNamespace(
            word=types.SimpleNamespace(), phone=types.SimpleNamespace()
        )
        spans = module.set_spans(models, np.zeros(75 * 16000))
        self.assertEqual(spans, [(16000, 496000), (496000, 976000), (976000, 1040000)])
        self.assertEqual(models.word.spans, models.phone.spans)
