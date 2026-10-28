"""Smoke-check the speech runtime inside the worker-media image (#232; ADR 0072).

Run it inside the image, on any architecture:

  docker run --rm -v "$PWD/infra/scripts:/checks:ro" <worker-media image> \
    python /checks/check-speech-runtime.py

It prints the measurements and exits 1 when one is out of bounds:
  - the speech libraries import, and the image has no compiler (ADR 0072);
  - praat-parselmouth gives the same pitch and intensity for a synthetic tone as on
    amd64 (the arm64 wheel is compiled from source, so this proves the build);
  - the production alignment model (wav2vec2, dynamic int8 linear layers, as in
    ai.yaml) agrees with its fp32 form on real speech. The quantised engine differs on
    Arm, so this runs on every architecture the image is published for.

The model and a 3-second speech clip are downloaded from download.pytorch.org
(about 360 MB), so the check needs network access and writes under TORCH_HOME.
"""

import platform
import shutil
import sys
from pathlib import Path

import numpy as np

# Measured on amd64 (worker-media, torch 2.8.0+cpu, praat-parselmouth 0.4.7).
PRAAT_F0_HZ = 219.999689
PRAAT_INTENSITY_DB = 80.969283
PRAAT_TOLERANCE_HZ = 0.01
PRAAT_TOLERANCE_DB = 0.01
# int8 versus fp32 on the clip below, measured on amd64: the share of frames where both
# pick the same character, and the mean absolute log-probability difference. They are
# low because dynamic int8 is lossy (ADR 0034 leaves its validation pending); this check
# only requires that another architecture behaves the same way, not that int8 is good.
INT8_AGREEMENT_AMD64 = 0.8521
INT8_AGREEMENT_TOLERANCE = 0.05
INT8_DRIFT_AMD64 = 2.0019
INT8_DRIFT_TOLERANCE = 0.3
CLIP = "tutorial-assets/Lab41-SRI-VOiCES-src-sp0307-ch127535-sg0042.wav"
COMPILERS = ("gcc", "g++", "cc", "cmake", "make")

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("ok    " if ok else "FAIL  ") + message)
    if not ok:
        failures.append(message)


def praat() -> None:
    import parselmouth

    t = np.arange(16000) / 16000
    tone = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 440 * t)
    sound = parselmouth.Sound(tone, sampling_frequency=16000)
    f0 = sound.to_pitch().selected_array["frequency"]
    f0_mean = float(f0[f0 > 0].mean())
    intensity = float(sound.to_intensity().values.mean())
    print(f"praat f0_mean={f0_mean:.6f} intensity_mean={intensity:.6f}")
    check(abs(f0_mean - PRAAT_F0_HZ) <= PRAAT_TOLERANCE_HZ, "Praat pitch matches amd64")
    check(
        abs(intensity - PRAAT_INTENSITY_DB) <= PRAAT_TOLERANCE_DB, "Praat intensity matches amd64"
    )


def int8_agreement() -> None:
    import torch
    import torchaudio

    from listenup.ai.providers.audio import decode_pcm

    torch.set_num_threads(2)
    print("quantized engines:", torch.backends.quantized.supported_engines)
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    clip = Path(torchaudio.utils.download_asset(CLIP))
    pcm = decode_pcm(clip, bundle.sample_rate)
    wave = torch.frombuffer(bytearray(pcm), dtype=torch.float32).unsqueeze(0)
    fp32 = bundle.get_model().eval()
    int8 = torch.ao.quantization.quantize_dynamic(
        bundle.get_model().eval(), {torch.nn.Linear}, dtype=torch.qint8
    )
    with torch.inference_mode():
        reference, _ = fp32(wave)
        quantised, _ = int8(wave)
    agreement = float((reference.argmax(-1) == quantised.argmax(-1)).float().mean())
    drift = float((reference.log_softmax(-1) - quantised.log_softmax(-1)).abs().mean())
    print(f"wav2vec2 frames={reference.shape[1]} int8_agreement={agreement:.4f}")
    print(f"wav2vec2 mean_logprob_drift={drift:.4f}")
    check(bool(torch.isfinite(quantised).all()), "int8 emissions are finite")
    check(
        abs(agreement - INT8_AGREEMENT_AMD64) <= INT8_AGREEMENT_TOLERANCE,
        "int8 agreement with fp32 matches amd64",
    )
    check(
        abs(drift - INT8_DRIFT_AMD64) <= INT8_DRIFT_TOLERANCE,
        "int8 log-probability drift matches amd64",
    )


def main() -> int:
    print(f"machine={platform.machine()} python={platform.python_version()}")
    import ctranslate2
    import faster_whisper  # noqa: F401
    import parselmouth
    import torch
    import torchaudio

    print(
        f"parselmouth={parselmouth.VERSION} torch={torch.__version__} "
        f"torchaudio={torchaudio.__version__} ctranslate2={ctranslate2.__version__}"
    )
    found = [name for name in COMPILERS if shutil.which(name)]
    check(not found, f"the image contains no compiler (found: {found})")
    praat()
    int8_agreement()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
