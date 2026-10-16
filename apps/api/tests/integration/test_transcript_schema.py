"""The cache is shared, worker-only, and database-enforced (#45)."""

import uuid

import psycopg
import pytest

from tests.integration.seed import seed_learner_data


def test_exclusion_rejects_overlap(migrated_url, learner):
    world = seed_learner_data(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn:
        for left, right in [(0, 10000), (10000, 20000)]:
            conn.execute(
                "INSERT INTO content.passage_transcripts (id, media_object_id, span, origin) "
                "VALUES (%s, %s, int4range(%s,%s), 'generated')",
                [uuid.uuid4(), world.media_id, left, right],
            )
        with pytest.raises(psycopg.errors.ExclusionViolation), conn.transaction():
            conn.execute(
                "INSERT INTO content.passage_transcripts (id, media_object_id, span, origin) "
                "VALUES (%s, %s, '[5000,15000)', 'generated')",
                [uuid.uuid4(), world.media_id],
            )


def test_api_cannot_read_shared_transcripts(api_role_url):
    with psycopg.connect(api_role_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM content.passage_transcripts")


@pytest.mark.parametrize("span", ["[0,)", "(,100)", "empty", "[-1,100)"])
def test_cache_span_must_be_finite_nonempty_and_nonnegative(migrated_url, learner, span):
    world = seed_learner_data(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO content.passage_transcripts (id, media_object_id, span, origin) "
            "VALUES (%s, %s, %s, 'generated')",
            [uuid.uuid4(), world.media_id, span],
        )


def test_concurrent_database_writers_cannot_overlap(migrated_url, learner):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    world = seed_learner_data(migrated_url, learner)
    started = threading.Event()
    writer_pids = []
    statement = (
        "INSERT INTO content.passage_transcripts (id,media_object_id,span,origin) "
        "VALUES (%s,%s,%s,'generated')"
    )

    def competing_insert():
        with psycopg.connect(migrated_url) as conn:
            conn.execute("SET statement_timeout='5s'")
            writer_pids.append(conn.info.backend_pid)
            started.set()
            with pytest.raises(psycopg.errors.ExclusionViolation):
                conn.execute(statement, [uuid.uuid4(), world.media_id, "[5000,15000)"])

    with psycopg.connect(migrated_url) as first, ThreadPoolExecutor(max_workers=1) as pool:
        first.execute(statement, [uuid.uuid4(), world.media_id, "[0,10000)"])
        contender = pool.submit(competing_insert)
        assert started.wait(3)
        # Observe the actual uncommitted-range conflict before releasing the winner.
        with psycopg.connect(migrated_url, autocommit=True) as observer:
            deadline = time.monotonic() + 3
            while not observer.execute("SELECT pg_blocking_pids(%s)", [writer_pids[0]]).fetchone()[
                0
            ]:
                assert time.monotonic() < deadline, "the competing insert must block"
                if contender.done():
                    contender.result()
        first.commit()
        contender.result(timeout=6)


@pytest.mark.parametrize(
    "assignment",
    [
        "confidence=ARRAY[-1]::int2[]",
        "confidence=ARRAY[NULL]::int2[]",
        "confidence=ARRAY[1001]::int2[]",
        "sentence_starts=ARRAY[-1]",
        "sentence_starts=ARRAY[NULL]::int4[]",
        "sentence_starts=ARRAY[1]",
        "provider_info='{}'::jsonb",
        """provider_info='["provider","model","version"]'::jsonb""",
        """provider_info='{"provider":"test","model":"speech"}'::jsonb""",
        """provider_info='{"provider":"","model":"speech","version":"1"}'::jsonb""",
        """provider_info='{"provider":"test","model":null,"version":"1"}'::jsonb""",
        """provider_info='{"provider":"test","model":"speech","version":2}'::jsonb""",
    ],
)
def test_ready_cache_rejects_invalid_confidence_sentence_indexes_and_provenance(
    migrated_url, learner, assignment
):
    world = seed_learner_data(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn:
        identifier = uuid.uuid4()
        conn.execute(
            """INSERT INTO content.passage_transcripts
            (id,media_object_id,span,origin,status,words,start_ms,end_ms,confidence,
             sentence_starts,provider_info)
            VALUES (%s,%s,'[0,10000)','generated','ready',ARRAY['Hello.'],ARRAY[100],
                    ARRAY[200],ARRAY[900],ARRAY[0],
                    '{"provider":"test","model":"speech","version":"1"}')""",
            [identifier, world.media_id],
        )
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute(
                "UPDATE content.passage_transcripts SET " + assignment + " WHERE id=%s",
                [identifier],
            )
