"""Content-free administrator usage reports, using the restricted report role (#100)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from listenup.platform.clock import server_now
from tests.integration.conftest import conninfo_to_url
from tests.integration.test_admin import AdminFactory
from tests.integration.test_admin import accounts as accounts

NOW = datetime(2026, 10, 30, 23, 30, tzinfo=UTC)


@pytest.fixture
def report_url(migrated_url: str) -> str:
    with psycopg.connect(migrated_url, autocommit=True) as db:
        db.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='listenup_report_test') THEN
                CREATE ROLE listenup_report_test LOGIN PASSWORD 'report-test';
              END IF;
              GRANT listenup_readonly TO listenup_report_test;
            END $$;
        """)
    params = psycopg.conninfo.conninfo_to_dict(migrated_url)
    params.update(user="listenup_report_test", password="report-test")
    return conninfo_to_url(psycopg.conninfo.make_conninfo(**params))


@pytest.fixture
def usage_config(tmp_path: Path) -> str:
    path = tmp_path / "ai.yaml"
    path.write_text("""version: 1
roles:
  text_ai:
    - provider: hosted
      limits:
        day: {calls: 10, tokens: 1000}
        month: {calls: 100, tokens: 10000}
      options: {api_key_env: NEVER_RETURN_THIS}
    - provider: local
      local: true
      limits: {day: {calls: 0}}
""")
    return str(path)


@pytest.fixture
def usage_rows(migrated_url: str):
    with psycopg.connect(migrated_url, autocommit=True) as db:
        db.execute("DELETE FROM ai.calls; DELETE FROM ai.quota_usage")
        db.execute("""
            CREATE TABLE IF NOT EXISTS ai.calls_2026_10 PARTITION OF ai.calls
            FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
        """)
        for at, outcome, inputs, outputs, estimated in [
            ("2026-10-01T00:00:00Z", "ok", 20, 5, False),
            ("2026-10-30T01:00:00Z", "ok", 100, 20, False),
            ("2026-10-30T02:00:00Z", "timeout", 200, 30, True),
            ("2026-10-30T03:00:00Z", "quota", 0, 0, True),
            ("2026-10-30T23:45:00Z", "ok", 999, 999, False),
        ]:
            db.execute(
                """
                INSERT INTO ai.calls
                (id, created_at, role, task, provider, model, input_units, output_units,
                 audio_seconds, projected_cost_usd, usage_estimated, outcome)
                VALUES (%s,%s,'text_ai','private-task','hosted','private-model',%s,%s,2,0.125,%s,%s)
            """,
                [uuid.uuid4(), at, inputs, outputs, estimated, outcome],
            )
        for period, at, calls, units in [
            ("day", "2026-10-30", 2, 350),
            ("month", "2026-10-01", 3, 375),
            ("minute", "2026-10-30T02:00:00Z", 99, 9999),
        ]:
            db.execute(
                """INSERT INTO ai.quota_usage
                (provider,period,period_start,calls,units,audio_seconds)
                VALUES ('hosted',%s,%s,%s,%s,4)""",
                [period, at, calls, units],
            )
    yield
    with psycopg.connect(migrated_url, autocommit=True) as db:
        db.execute("DELETE FROM ai.calls; DELETE FROM ai.quota_usage")


def test_usage_aggregates_30_utc_days_without_double_counting(
    accounts: AdminFactory, report_url: str, usage_config: str, usage_rows: None
) -> None:
    client = accounts(admin_report_database_url=report_url, ai_config=usage_config)
    client.app.dependency_overrides[server_now] = lambda: NOW
    response = client.get("/api/v1/admin/usage")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["start_date"] == "2026-10-01"
    assert data["end_date"] == "2026-10-30"
    hosted = next(p for p in data["providers"] if p["provider"] == "hosted")
    assert len(hosted["days"]) == 30
    assert hosted["days"][0]["calls"] == 1
    assert hosted["days"][1]["calls"] == 0
    assert hosted["days"][-1] == {
        "date": "2026-10-30",
        "calls": 2,
        "input_tokens": 300,
        "output_tokens": 50,
        "audio_seconds": 4.0,
        "estimated_cost_usd": 0.25,
        "estimated_calls": 1,
    }
    assert hosted["quotas"][0] == {
        "period": "day",
        "calls": 2,
        "tokens": 350,
        "audio_seconds": 4.0,
        "limits": {"calls": 10, "tokens": 1000},
    }
    assert hosted["quotas"][1]["calls"] == 3
    assert "private-task" not in response.text
    assert "private-model" not in response.text
    assert "NEVER_RETURN_THIS" not in response.text


@pytest.mark.parametrize("admin,verified", [(False, True), (True, False)])
def test_usage_is_hidden_from_non_admins(accounts: AdminFactory, admin: bool, verified: bool):
    response = accounts(admin=admin, verified=verified).get("/api/v1/admin/usage")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_usage_without_report_connection_is_explicitly_unavailable(accounts: AdminFactory):
    response = accounts().get("/api/v1/admin/usage")
    assert response.status_code == 503
    assert response.json()["code"] == "usage_unavailable"


def test_usage_preserves_zero_uncapped_and_unknown_limits(
    accounts: AdminFactory,
    report_url: str,
    usage_config: str,
    usage_rows: None,
    migrated_url: str,
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as db:
        db.execute("""INSERT INTO ai.quota_usage (provider,period,period_start,calls)
            VALUES ('removed-provider','day','2026-10-30',1)""")
    client = accounts(admin_report_database_url=report_url, ai_config=usage_config)
    client.app.dependency_overrides[server_now] = lambda: NOW
    data = client.get("/api/v1/admin/usage").json()
    local = next(p for p in data["providers"] if p["provider"] == "local")
    assert local["quotas"][0]["limits"] == {"calls": 0}
    assert local["quotas"][1]["limits"] == {}
    assert all(day["calls"] == 0 for day in local["days"])
    removed = next(p for p in data["providers"] if p["provider"] == "removed-provider")
    assert removed["quotas"][0]["limits"] is None
    assert removed["quotas"][0]["calls"] == 1


def test_usage_empty_report_and_utc_boundary(
    accounts: AdminFactory,
    report_url: str,
    usage_config: str,
    usage_rows: None,
) -> None:
    client = accounts(admin_report_database_url=report_url, ai_config=usage_config)
    # Local Nov 1 is still Oct 31 UTC. The Oct 1 call is now outside the range.
    client.app.dependency_overrides[server_now] = lambda: datetime.fromisoformat(
        "2026-11-01T00:00:00+02:00"
    )
    data = client.get("/api/v1/admin/usage").json()
    assert data["start_date"] == "2026-10-02"
    assert data["end_date"] == "2026-10-31"
    hosted = next(p for p in data["providers"] if p["provider"] == "hosted")
    assert sum(day["calls"] for day in hosted["days"]) == 3
    Path(usage_config).write_text("roles: {}")
    client.app.dependency_overrides[server_now] = lambda: datetime(2026, 12, 30, tzinfo=UTC)
    assert client.get("/api/v1/admin/usage").json()["providers"] == []


@pytest.mark.parametrize(
    "contents",
    [
        "roles: [not-a-mapping]",
        "roles: {text_ai: [{provider: hosted, limits: {day: {calls: -1}}}]}",
        "roles: {text_ai: [{provider: hosted, limits: {day: {calls: .inf}}}]}",
        "roles: {text_ai: [{provider: same}, {provider: same, limits: {day: {calls: 1}}}]}",
        "[invalid: yaml",
    ],
)
def test_usage_invalid_config_is_unavailable_without_leaking_details(
    accounts: AdminFactory,
    report_url: str,
    usage_config: str,
    contents: str,
) -> None:
    Path(usage_config).write_text(contents)
    client = accounts(admin_report_database_url=report_url, ai_config=usage_config)
    response = client.get("/api/v1/admin/usage")
    assert response.status_code == 503
    assert response.json()["detail"] == "Usage reporting is unavailable."
    assert usage_config not in response.text


def test_usage_missing_config_is_unavailable(accounts: AdminFactory, report_url: str):
    client = accounts(admin_report_database_url=report_url, ai_config="/missing/secret-config")
    assert client.get("/api/v1/admin/usage").status_code == 503


def test_usage_does_not_fall_back_to_the_api_role(
    accounts: AdminFactory,
    api_role_url: str,
    usage_config: str,
) -> None:
    client = accounts(admin_report_database_url=api_role_url, ai_config=usage_config)
    response = client.get("/api/v1/admin/usage")
    assert response.status_code == 503
    assert response.json()["detail"] == "Usage reporting is unavailable."
    assert api_role_url not in response.text


def test_report_login_has_no_identity_or_accounting_write_access(report_url: str):
    with psycopg.connect(report_url) as db:
        db.execute("SET LOCAL ROLE listenup_readonly")
        assert db.execute("SELECT current_user").fetchone() == ("listenup_readonly",)
        assert db.execute("SELECT has_table_privilege('ai.calls','SELECT')").fetchone() == (True,)
        assert db.execute("SELECT has_table_privilege('ai.calls','INSERT')").fetchone() == (False,)
        assert db.execute("SELECT has_table_privilege('ai.quota_usage','UPDATE')").fetchone() == (
            False,
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT email FROM identity.users")
