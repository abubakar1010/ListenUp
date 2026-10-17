"""Persistent admission across independent gateway processes/connections (#64)."""

import asyncio
from uuid import uuid4

import psycopg
import pytest

from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import ProviderEntry
from listenup.ai.ports import Role, Usage
from listenup.platform.database import Database
from tests.integration.conftest import conninfo_to_url


@pytest.mark.anyio
async def test_concurrent_admission_never_exceeds_quota(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    provider = "p" + uuid4().hex
    entry = ProviderEntry(
        provider=provider, limits={"day": {"calls": 3, "tokens": 30}, "month": {"calls": 5}}
    )
    try:
        stores = [PostgresAccounting(db) for _ in range(12)]
        tickets = await asyncio.gather(
            *(
                s.admit(
                    entry,
                    Role.TEXT_AI,
                    "grade_gist",
                    "v1",
                    Usage(input_tokens=4, output_tokens=6),
                    False,
                )
                for s in stores
            )
        )
        assert sum(t is not None for t in tickets) == 3
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT calls, units FROM ai.quota_usage WHERE provider=%s AND period='day'",
                [provider],
            ).fetchone() == (3, 30)
        # A new object sees exhausted persisted counters, not a process-local cache.
        assert (
            await PostgresAccounting(db).admit(
                entry, Role.TEXT_AI, "grade_gist", "v1", Usage(), False
            )
            is None
        )
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_settlement_is_idempotent_and_counts_actual_usage(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    provider = "p" + uuid4().hex
    entry = ProviderEntry(provider=provider, limits={"day": {"tokens": 100}})
    store = PostgresAccounting(db)
    try:
        ticket = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=40, output_tokens=20), False
        )
        assert ticket is not None
        await store.finish(
            ticket,
            "ok",
            12,
            "engine-v1",
            Usage(input_tokens=10, output_tokens=5, reasoning_tokens=2, cache_tokens=3),
        )
        await store.finish(ticket, "ok", 12, "engine-v1", Usage(input_tokens=1))
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT calls, units FROM ai.quota_usage WHERE provider=%s AND period='day'",
                [provider],
            ).fetchone() == (1, 15)
            row = conn.execute(
                "SELECT "
                "role,task,provider,model,version,prompt_version,outcome,input_units,"
                "output_units,reasoning_tokens,cache_tokens "
                "FROM ai.calls WHERE provider=%s",
                [provider],
            ).fetchone()
            assert row == (
                "text_ai",
                "grade_gist",
                provider,
                "default",
                "engine-v1",
                "v1",
                "ok",
                10,
                5,
                2,
                3,
            )
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_rate_limit_and_monthly_audio_exhaustion(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    store = PostgresAccounting(db)
    try:
        for limits, budget in [
            ({"minute": {"calls": 1}}, Usage()),
            ({"month": {"audio_seconds": 10}}, Usage(audio_seconds=6)),
        ]:
            entry = ProviderEntry(provider="p" + uuid4().hex, limits=limits)
            assert await store.admit(entry, Role.TRANSCRIPTION, "transcribe", None, budget, False)
            assert (
                await store.admit(entry, Role.TRANSCRIPTION, "transcribe", None, budget, False)
                is None
            )
    finally:
        await db.dispose()


def test_ai_logs_are_content_free_and_api_cannot_write(conn):
    columns = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='ai' AND "
            "table_name='calls'"
        )
    }
    assert not columns & {
        "user_id",
        "email",
        "input",
        "output",
        "error",
        "job_id",
        "request_id",
        "context",
    }
    assert {
        "provider",
        "model",
        "version",
        "prompt_version",
        "outcome",
        "input_units",
        "output_units",
    } <= columns
    assert conn.execute(
        "SELECT has_table_privilege('listenup_api','ai.calls','SELECT'), "
        "has_table_privilege('listenup_api','ai.calls','INSERT')"
    ).fetchone() == (True, False)


@pytest.mark.anyio
async def test_failed_calls_keep_reservations_and_month_denial_is_atomic(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    store = PostgresAccounting(db)
    entry = ProviderEntry(
        provider="p" + uuid4().hex, limits={"day": {"calls": 10}, "month": {"calls": 1}}
    )
    try:
        ticket = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=20), False
        )
        await store.finish(ticket, "timeout", 100, None, None)
        assert await store.admit(entry, Role.TEXT_AI, "grade_gist", "v1", Usage(), False) is None
        with psycopg.connect(migrated_url) as conn:
            assert (
                conn.execute(
                    "SELECT calls, units FROM ai.quota_usage WHERE provider=%s ORDER BY period",
                    [entry.provider],
                ).fetchall()
                == [(1, 20)] * 3
            )
            assert conn.execute(
                "SELECT outcome FROM ai.calls WHERE provider=%s ORDER BY created_at",
                [entry.provider],
            ).fetchall() == [("timeout",), ("quota",)]
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_routine_requests_leave_reserved_grading_headroom(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    store = PostgresAccounting(db)
    entry = ProviderEntry(
        provider="p" + uuid4().hex, limits={"day": {"calls": 4}}, grading_reserve=0.25
    )
    try:
        for _ in range(3):
            assert await store.admit(entry, Role.TEXT_AI, "suggestions", "v1", Usage(), True)
        assert await store.admit(entry, Role.TEXT_AI, "suggestions", "v1", Usage(), True) is None
        assert await store.remaining(entry) == 0.25
        assert await store.admit(entry, Role.TEXT_AI, "grade_gist", "v1", Usage(), False)
        assert await store.remaining(entry) == 0
    finally:
        await db.dispose()


def test_partitions_cover_next_three_months_and_maintenance_is_restricted(conn):
    assert (
        conn.execute(
            "SELECT count(*) FROM pg_inherits WHERE inhparent='ai.calls'::regclass"
        ).fetchone()[0]
        >= 4
    )
    assert conn.execute(
        "SELECT "
        "has_function_privilege('listenup_worker','ai.maintain_partitions()','EXECUTE'), "
        "has_function_privilege('listenup_api','ai.maintain_partitions()','EXECUTE')"
    ).fetchone() == (True, False)


@pytest.mark.anyio
async def test_projected_cost_is_metered_without_paid_routing(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    entry = ProviderEntry(
        provider="p" + uuid4().hex,
        projected_input_cost_per_million=1,
        projected_output_cost_per_million=2,
    )
    store = PostgresAccounting(db)
    try:
        ticket = await store.admit(
            entry,
            Role.TEXT_AI,
            "grade_gist",
            "v1",
            Usage(input_tokens=100, output_tokens=50),
            False,
            fallback_depth=2,
            queue_delay_ms=50,
        )
        await store.finish(ticket, "ok", 10, "v1", Usage(input_tokens=10, output_tokens=5))
        with psycopg.connect(migrated_url) as conn:
            cost, depth, delay = conn.execute(
                "SELECT projected_cost_usd,fallback_depth,queue_delay_ms FROM ai.calls WHERE "
                "provider=%s",
                [entry.provider],
            ).fetchone()
            assert cost == pytest.approx(0.00002)
            assert (depth, delay) == (2, 50)
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_scheduled_maintenance_updates_quota_metrics_and_partitions(migrated_url):
    from listenup.ai.jobs import maintain
    from listenup.platform.jobs import JobDeps

    db = Database(conninfo_to_url(migrated_url))
    try:
        await maintain(JobDeps(db, None, 1))
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_gateway_fallback_persists_content_free_attempts(migrated_url):
    from pathlib import Path

    from listenup.ai.config import AIConfig
    from listenup.ai.gateway import AIGateway
    from listenup.ai.ports import Provenance, Transcript
    from listenup.ai.registry import Registry
    from tests.telemetry_helpers import capture

    db = Database(conninfo_to_url(migrated_url))
    first, second = "p" + uuid4().hex, "p" + uuid4().hex
    calls = []

    class Adapter:
        def __init__(self, entry):
            self.entry = entry

        async def transcribe(self, audio, language):
            calls.append(self.entry.provider)
            if self.entry.provider == first:
                raise ValueError("learner@example.com private content")
            return Transcript(
                provenance=Provenance(provider=second, model="m", version="v1"),
                language="en",
                duration_seconds=2,
                segments=(),
            )

    entries = tuple(
        ProviderEntry(provider=p, model="m", local=True, trains_on_inputs=False, retries=0)
        for p in (first, second)
    )
    gateway = AIGateway(
        AIConfig(version=1, roles={Role.TRANSCRIPTION: entries}),
        registry=Registry(transcription={first: Adapter, second: Adapter}),
        accounting=PostgresAccounting(db),
    )
    try:
        with capture() as telemetry:
            result = await gateway.transcribe(Path("users/learner@example.com/private.wav"))
            assert result.provenance.provider == second
            assert "learner@" not in telemetry.everything()
            assert "private" not in telemetry.everything()
        with psycopg.connect(migrated_url) as conn:
            rows = conn.execute(
                "SELECT row_to_json(c)::text FROM ai.calls c WHERE provider=ANY(%s) "
                "ORDER BY created_at",
                [[first, second]],
            ).fetchall()
            assert len(rows) == 2
            assert "learner@" not in repr(rows) and "private" not in repr(rows)
            assert '"outcome":"error"' in rows[0][0] and '"outcome":"ok"' in rows[1][0]
        assert calls == [first, second]
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_reset_and_settlement_use_original_utc_buckets(migrated_url):
    from datetime import timedelta

    db = Database(conninfo_to_url(migrated_url))
    store = PostgresAccounting(db)
    entry = ProviderEntry(provider="p" + uuid4().hex, limits={"day": {"calls": 1, "tokens": 100}})
    with psycopg.connect(migrated_url) as conn:
        today = conn.execute("SELECT now()").fetchone()[0]
    before = today.replace(hour=23, minute=59, second=59, microsecond=0)
    after = before + timedelta(seconds=2)

    async def clock_before(_):
        return before

    async def clock_after(_):
        return after

    try:
        store._now = clock_before
        old = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=40), False
        )
        store._now = clock_after
        new = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=30), False
        )
        assert old and new
        await store.finish(old, "ok", 1, "v1", Usage(input_tokens=10))
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT calls,units FROM ai.quota_usage WHERE provider=%s "
                "AND period='day' ORDER BY period_start",
                [entry.provider],
            ).fetchall() == [(1, 10), (1, 30)]
    finally:
        await db.dispose()


def test_partition_retention_drops_only_expired_months(conn):
    conn.execute("""DO $$ DECLARE start_at timestamptz :=
 date_trunc('month',now()) - interval '6 months';
    BEGIN EXECUTE format('CREATE TABLE ai.calls_%s PARTITION OF ai.calls
      FOR VALUES FROM (%L) TO (%L)',
      to_char(start_at,'YYYY_MM'), start_at,start_at+interval '1 month'); END $$;""")
    before = conn.execute(
        "SELECT count(*) FROM pg_inherits WHERE inhparent='ai.calls'::regclass"
    ).fetchone()[0]
    conn.execute("SELECT ai.maintain_partitions()")
    assert (
        conn.execute(
            "SELECT count(*) FROM pg_inherits WHERE inhparent='ai.calls'::regclass"
        ).fetchone()[0]
        == before - 1
    )


@pytest.mark.anyio
async def test_worker_role_admits_but_api_role_cannot_write(migrated_url, api_role_url):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    db = Database(conninfo_to_url(migrated_url))
    api = Database(api_role_url)
    try:
        # Execute the actual gateway operations with exactly the worker's privileges.
        async with db.transaction() as session:
            await session.execute(text("SET ROLE listenup_worker"))
            await session.execute(text("SELECT ai.maintain_partitions()"))
            await session.execute(
                text(
                    "INSERT INTO ai.quota_usage(provider,period,period_start) "
                    "VALUES ('worker-test','day',now())"
                )
            )
        with pytest.raises(DBAPIError):
            await PostgresAccounting(api).admit(
                ProviderEntry(provider="denied"), Role.TEXT_AI, "grade_gist", "v1", Usage(), False
            )
    finally:
        await db.dispose()
        await api.dispose()


@pytest.mark.anyio
async def test_logs_distinguish_actual_usage_from_reservations(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    store = PostgresAccounting(db)
    entry = ProviderEntry(provider="p" + uuid4().hex)
    try:
        one = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=10), False
        )
        two = await store.admit(
            entry, Role.TEXT_AI, "grade_gist", "v1", Usage(input_tokens=10), False
        )
        await store.finish(one, "ok", 1, "v1", Usage(input_tokens=5))
        await store.finish(two, "ok", 1, "v1", None)
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT input_units,usage_estimated FROM ai.calls "
                "WHERE provider=%s ORDER BY created_at",
                [entry.provider],
            ).fetchall() == [(5, False), (10, True)]
    finally:
        await db.dispose()


@pytest.mark.anyio
async def test_skipped_provider_is_logged_without_quota_charge(migrated_url):
    db = Database(conninfo_to_url(migrated_url))
    entry = ProviderEntry(provider="p" + uuid4().hex)
    store = PostgresAccounting(db)
    try:
        await store.skip(entry, Role.TEXT_AI, "grade_gist", "v1", "ineligible")
        with psycopg.connect(migrated_url) as conn:
            assert conn.execute(
                "SELECT outcome,input_units,output_units FROM ai.calls WHERE provider=%s",
                [entry.provider],
            ).fetchall() == [("ineligible", 0, 0)]
            assert (
                conn.execute(
                    "SELECT count(*) FROM ai.quota_usage WHERE provider=%s", [entry.provider]
                ).fetchone()[0]
                == 0
            )
    finally:
        await db.dispose()


def test_schema_check_ignores_only_monthly_partition_names(make_database):
    from alembic import command
    from alembic.util.exc import AutogenerateDiffsDetected

    from tests.integration.conftest import alembic_config

    url = make_database()
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.check(config)  # the real monthly partitions are allowed
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE TABLE ai.calls_unexpected (id integer)")
    with pytest.raises(AutogenerateDiffsDetected):
        command.check(config)
