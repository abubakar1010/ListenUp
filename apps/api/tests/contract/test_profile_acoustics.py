"""Real Parselmouth on deterministic PCM: acoustics, not model quality evidence."""

import math
import struct
import wave

import pytest


def write_tone(path, seconds=1, frequency=200, amplitude=0.2):
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        output.writeframes(
            b"".join(
                struct.pack(
                    "<h", round(amplitude * 32767 * math.sin(2 * math.pi * frequency * i / 16000))
                )
                for i in range(round(seconds * 16000))
            )
        )


def test_real_pitch_intensity_and_provenance(tmp_path):
    pytest.importorskip("parselmouth")
    from listenup.ai.providers.parselmouth_acoustics import extract

    audio = tmp_path / "tone.wav"
    write_tone(audio)
    track = extract(audio, 1000)
    assert len(track.pitch_cents) == len(track.intensity_cdb) == 50
    voiced = [v for v in track.pitch_cents if v is not None]
    assert len(voiced) >= 40
    assert all(abs(v - 9173) < 20 for v in voiced)  # 1200 log2(200 Hz / 1 Hz)
    assert all(v is None or 5000 < v < 10000 for v in track.intensity_cdb)
    assert track.provenance["version"] == "0.4.7"
    assert track.provenance["praat_version"]
    assert track.provenance["settings"]["frame_step_ms"] == 20


def test_real_silence_is_unobservable_not_perfect(tmp_path):
    pytest.importorskip("parselmouth")
    from listenup.ai.providers.parselmouth_acoustics import extract

    audio = tmp_path / "silence.wav"
    write_tone(audio, amplitude=0)
    track = extract(audio, 1000)
    assert track.pitch_cents == [None] * 50
    assert track.intensity_cdb == [None] * 50


def test_short_window_retains_unknown_frames(tmp_path):
    from listenup.ai.providers.parselmouth_acoustics import extract

    audio = tmp_path / "short.wav"
    write_tone(audio, seconds=0.02)
    track = extract(audio, 20)
    assert track.pitch_cents == [None]
    assert track.intensity_cdb == [None]
