"""#67: the shared reference is valid, durable, private and extracted once."""

import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.integration.seed import add_clip

POINTS = [
    {"id": "kp1", "text": "Cities plant trees to cool streets.", "kind": "main"},
    {"id": "kp2", "text": "Trees shade the pavement.", "kind": "supporting"},
    {"id": "kp3", "text": "Leaves release water.", "kind": "supporting"},
]
PROVENANCE = {"provider": "test", "model": "text-model", "version": "deployment-1"}


@pytest.fixture
def clip(migrated_url, learner):
    return add_clip(migrated_url, learner)[:2]


@pytest.fixture
def conn(migrated_url, clip):
    # Roll back the cache insert before the learner fixture cascades its media.
    with psycopg.connect(migrated_url) as connection:
        yield connection
        connection.rollback()


def insert(conn, media, points=POINTS, provenance=PROVENANCE, version="v1", span="[0,120000)"):
    conn.execute(
        "INSERT INTO grading.key_points "
        "(id, media_object_id, span, prompt_version, points, provider_info) "
        "VALUES (%s, %s, %s::int4range, %s, %s, %s)",
        [uuid.uuid4(), media, span, version, Jsonb(points), Jsonb(provenance)],
    )


def test_stores_valid_key_points_with_provenance(conn, clip):
    insert(conn, clip[0])
    assert conn.execute(
        "SELECT prompt_version, points, provider_info FROM grading.key_points "
        "WHERE media_object_id=%s",
        [clip[0]],
    ).fetchone() == ("v1", POINTS, PROVENANCE)


@pytest.mark.parametrize(
    "points",
    [
        [],
        POINTS[:2],
        POINTS + POINTS + POINTS[:1],
        [dict(p, kind="supporting") for p in POINTS],
        [POINTS[1], POINTS[0], POINTS[2]],
        [POINTS[0], POINTS[0], POINTS[2]],
        [dict(POINTS[0], text=""), *POINTS[1:]],
        [dict(POINTS[0], kind="other"), *POINTS[1:]],
        {"key_points": POINTS},
    ],
)
def test_database_rejects_invalid_points(conn, clip, points):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(conn, clip[0], points=points)


@pytest.mark.parametrize(
    "provenance", [{}, {**PROVENANCE, "model": ""}, {**PROVENANCE, "provider": 1}]
)
def test_database_requires_result_provenance(conn, clip, provenance):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(conn, clip[0], provenance=provenance)


@pytest.mark.parametrize("span", ["empty", "(,120000)", "[0,)", "[-1,120000)"])
def test_database_requires_a_bounded_nonnegative_span(conn, clip, span):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(conn, clip[0], span=span)


def test_one_cache_entry_per_passage_and_version(conn, clip):
    insert(conn, clip[0])
    insert(conn, clip[0], version="v2")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert(conn, clip[0])


def test_cache_is_deleted_only_with_its_media(migrated_url, learner, clip):
    with psycopg.connect(migrated_url) as conn:
        insert(conn, clip[0])
        conn.execute("DELETE FROM content.contents WHERE id=%s", [clip[1]])
        assert conn.execute(
            "SELECT count(*) FROM grading.key_points WHERE media_object_id=%s", [clip[0]]
        ).fetchone() == (1,)
        conn.execute("DELETE FROM content.media_objects WHERE id=%s", [clip[0]])
        assert conn.execute(
            "SELECT count(*) FROM grading.key_points WHERE media_object_id=%s", [clip[0]]
        ).fetchone() == (0,)


def test_api_role_cannot_read_the_shared_cache(api_role_url, migrated_url, clip):
    with psycopg.connect(migrated_url) as conn:
        insert(conn, clip[0])
    with psycopg.connect(api_role_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM grading.key_points")
