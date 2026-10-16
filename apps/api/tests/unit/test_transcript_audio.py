import struct
import wave

import pytest

from listenup.modules.transcript.jobs import extract


@pytest.mark.anyio
async def test_extraction_seeks_to_requested_audio_and_keeps_duration(tmp_path):
    source, target = tmp_path / "source.wav", tmp_path / "gap.wav"
    with wave.open(str(source), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"".join(struct.pack("<h", value) * 16000 for value in (1000, 2000, 3000)))
    await extract(source, target, (1250, 2500))
    with wave.open(str(target)) as f:
        assert f.getframerate() == 16000
        assert f.getnchannels() == 1
        assert f.getnframes() == 20000
        samples = struct.unpack("<20000h", f.readframes(20000))
    assert samples[:12000] == (2000,) * 12000
    assert samples[12000:] == (3000,) * 8000
