"""Shared fixtures for the Dictation submission tests (#54)."""

import uuid

import psycopg

# A known passage: ten words, 1 s apart, starting at 1 s (AT-3 uses it as the reference).
REFERENCE_TEXT = "Cities plant street trees to cool the air in summer."
REFERENCE_WORDS = REFERENCE_TEXT.split()
PASSAGE = {"start_ms": 0, "end_ms": 120_000}


def media_of(owner_url: str, content_id: str) -> uuid.UUID:
    with psycopg.connect(owner_url) as conn:
        row = conn.execute(
            "SELECT media_object_id FROM content.contents WHERE id = %s", [content_id]
        ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def seed_transcript(
    owner_url: str, media_id: uuid.UUID, words: list[str] | None = None
) -> list[str]:
    """Cache a ready transcript for the first 125 s of a clip (passage plus padding)."""
    words = words if words is not None else REFERENCE_WORDS
    starts = [1000 * (i + 1) for i in range(len(words))]
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.passage_transcripts (id, media_object_id, span, origin, status, "
            "words, start_ms, end_ms, confidence, sentence_starts, provider_info) "
            "VALUES (%s, %s, int4range(0, 125000), 'generated', 'ready', %s, %s, %s, %s, %s, %s)",
            [
                uuid.uuid4(),
                media_id,
                words,
                starts,
                [s + 800 for s in starts],
                [900] * len(words),
                [0],
                psycopg.types.json.Jsonb({"provider": "test", "model": "speech", "version": "v1"}),
            ],
        )
    return words
