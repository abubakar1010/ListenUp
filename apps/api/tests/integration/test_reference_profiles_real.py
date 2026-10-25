"""Opt-in unmocked profile processing; requires local speech weights and public corpus.

This validates persisted size and the processing path, not boundary accuracy or
stage-0 latency. Normal CI covers contracts separately without downloading models.
"""

import json
import os
from pathlib import Path

import psycopg
import pytest

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import load_config
from listenup.ai.gateway import AIGateway
from listenup.modules.practice import service as practice
from listenup.modules.transcript import profile_jobs, profile_service
from listenup.modules.transcript.models import PassageTranscript
from listenup.platform.database import Database
from listenup.platform.ids import uuid7
from listenup.platform.jobs import JobDeps
from tests.integration.conftest import conninfo_to_url
from tests.integration.seed import add_clip
from tests.integration.test_storage import storage as storage_fixture

storage = storage_fixture


@pytest.mark.anyio
async def test_three_minute_profile_storage_under_50kb(migrated_url, learner, storage, monkeypatch):
    fixture = os.environ.get("LISTENUP_REAL_PROFILE_FIXTURE")
    if not fixture:
        pytest.skip(
            "Opt-in real-model run: set LISTENUP_REAL_PROFILE_FIXTURE to prepared "
            "LibriSpeech fixture"
        )
    root = Path(fixture)
    words = json.loads((root / "words.json").read_text())
    source = json.loads((root / "source.json").read_text())
    assert source["duration_seconds"] == 185
    media, content, _ = add_clip(migrated_url, learner)
    with psycopg.connect(migrated_url) as db:
        db.execute("UPDATE content.media_objects SET duration_ms=185000 WHERE id=%s", [media])
    database = Database(conninfo_to_url(migrated_url) + "?options=-crole%3Dlistenup_worker")
    gateway = AIGateway(load_config(), accounting=PostgresAccounting(database))
    monkeypatch.setattr(profile_jobs, "get_gateway", lambda: gateway)
    monkeypatch.setattr(profile_service, "get_gateway", lambda: gateway)
    monkeypatch.setattr(profile_jobs, "get_storage", lambda: storage)
    await storage.put_file(
        f"users/{learner}/media/{media}/playback.mp4", root / "reference.wav", "audio/wav"
    )
    try:
        from sqlalchemy.dialects.postgresql import Range

        async with database.transaction(learner) as db:
            session = await practice.start_plan(
                db, learner, content, 0, 180000, practice.Entry.BLIND
            )
            identifier = uuid7()
            # Input fixture: corpus words with synthetic cache timings. #76 recomputes
            # all alignment from audio; this is not evidence of real transcription.
            db.add(
                PassageTranscript(
                    id=identifier,
                    media_object_id=media,
                    span=Range(0, 185000),
                    origin="generated",
                    status="ready",
                    words=words,
                    start_ms=[i * 200 for i in range(len(words))],
                    end_ms=[i * 200 + 100 for i in range(len(words))],
                    confidence=[1000] * len(words),
                    sentence_starts=[0],
                    provider_info={
                        "provider": "human-fixture",
                        "model": "LibriSpeech",
                        "version": source["audio_sha256"],
                    },
                )
            )
        async with database.transaction(learner) as db:
            await profile_service.queue_profile(db, learner, session.id)
        with psycopg.connect(migrated_url) as db:
            fingerprint = db.execute(
                "SELECT fingerprint FROM content.profile_subscriptions WHERE session_id=%s",
                [session.id],
            ).fetchone()[0]
        await profile_jobs.profile_span(JobDeps(database, None, 1), str(identifier), fingerprint)
        with psycopg.connect(migrated_url) as db:
            row = db.execute(
                "SELECT "
                "status,pg_column_size(p),provenance,cardinality(word_indices),cardinality(pitch_cents)"
                " FROM content.reference_profiles p WHERE passage_transcript_id=%s",
                [identifier],
            ).fetchone()
            assert row[0] == "ready"
            assert row[1] <= 50000
            assert row[2]["alignment"]["model"] == "WAV2VEC2_ASR_BASE_960H"
            assert "window_seconds=30" in row[2]["alignment"]["version"]
            assert row[3] > 0 and row[4] == 9250
            assert db.execute(
                "SELECT status FROM content.profile_subscriptions WHERE session_id=%s", [session.id]
            ).fetchone() == ("ready",)
        evidence = {
            "profile_bytes": row[1],
            "provenance": row[2],
            "aligned_words": row[3],
            "input_words": len(words),
            "frames": row[4],
            "source": source,
            "performance": "stage-0 unverified; not a latency acceptance run",
        }
        (root / "result.json").write_text(json.dumps(evidence, indent=2))
    finally:
        await database.dispose()
