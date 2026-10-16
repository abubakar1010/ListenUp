"""Real storage and decoding boundary; fake AI proves plumbing, not model quality."""

import wave
from pathlib import Path

import psycopg
import pytest

from listenup.ai.config import FAKE_CONFIG, load_config
from listenup.ai.gateway import AIGateway
from listenup.modules.transcript import jobs
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError
from tests.integration.conftest import conninfo_to_url
from tests.integration.seed import add_clip
from tests.integration.test_passage_transcription import start
from tests.integration.test_storage import storage as storage_fixture

storage = storage_fixture


@pytest.mark.anyio
async def test_three_minute_passage_real_storage_decode_and_configured_gateway(
    migrated_url, learner, storage, tmp_path, monkeypatch
):
    media, content, _ = add_clip(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("UPDATE content.media_objects SET duration_ms=200000 WHERE id=%s", [media])
    audio = tmp_path / "source.wav"
    with wave.open(str(audio), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 16000 * 200)
    await storage.put_file(f"users/{learner}/media/{media}/playback.mp4", audio, "audio/wav")
    gateway = AIGateway(load_config(FAKE_CONFIG))
    decoded = []

    class CheckedGateway:
        async def transcribe(self, path, language):
            with wave.open(str(path), "rb") as reader:
                assert reader.getnchannels() == 1
                assert reader.getframerate() == 16000
                assert reader.getnframes() == 185 * 16000
            decoded.append(Path(path))
            return await gateway.transcribe(path, language)

    monkeypatch.setattr(jobs, "get_storage", lambda: storage)
    monkeypatch.setattr(jobs, "get_gateway", lambda: CheckedGateway())
    database = Database(conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker")
    try:
        session = await start(database, learner, content, 0, 180000)
        await jobs.transcribe_passage(JobDeps(database, None, 1), str(session.id), str(learner))
        with psycopg.connect(migrated_url) as conn:
            row = conn.execute(
                "SELECT words, provider_info, status FROM content.passage_transcripts WHERE "
                "media_object_id=%s",
                [media],
            ).fetchone()
        assert row[0] == ["this", "is", "a", "fake", "transcript"]
        assert row[1]["provider"] == "fake"
        assert row[2] == "ready"
        assert not decoded[0].parent.exists()
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_decode_failure_is_permanent_and_cleans_process(tmp_path):
    source = tmp_path / "bad.mp4"
    source.write_text("not audio")
    with pytest.raises(PermanentError):
        await jobs.extract(source, tmp_path / "window.wav", (0, 30000))
