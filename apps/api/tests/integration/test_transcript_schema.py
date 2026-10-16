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
    from concurrent.futures import ThreadPoolExecutor

    world = seed_learner_data(migrated_url, learner)
    started = threading.Event()
    statement = (
        "INSERT INTO content.passage_transcripts (id,media_object_id,span,origin) "
        "VALUES (%s,%s,%s,'generated')"
    )

    def competing_insert():
        with psycopg.connect(migrated_url) as conn:
            conn.execute("SET statement_timeout='5s'")
            started.set()
            with pytest.raises(psycopg.errors.ExclusionViolation):
                conn.execute(statement, [uuid.uuid4(), world.media_id, "[5000,15000)"])

    with psycopg.connect(migrated_url) as first, ThreadPoolExecutor(max_workers=1) as pool:
        first.execute(statement, [uuid.uuid4(), world.media_id, "[0,10000)"])
        contender = pool.submit(competing_insert)
        assert started.wait(3)
        first.commit()
        contender.result(timeout=6)
