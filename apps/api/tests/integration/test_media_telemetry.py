import asyncio
import base64
import json
from unittest.mock import AsyncMock

import httpx
import psycopg

from listenup.platform import telemetry_relay
from listenup.platform.config import Settings
from tests.integration.conftest import conninfo_to_url


def test_media_batch_is_persisted_then_exported_by_default_pool(migrated_url, monkeypatch):
    settings = Settings(
        database_url=conninfo_to_url(migrated_url),
        otel_enabled=True,
        otel_metrics_endpoint="https://collector/v1/metrics",
    )
    monkeypatch.setattr(telemetry_relay, "get_settings", lambda: settings)
    payload = b"content-free telemetry"
    telemetry_relay.submit("metrics", payload)
    with psycopg.connect(migrated_url) as connection:
        rows = connection.execute(
            "SELECT queue_name, args FROM procrastinate.procrastinate_jobs WHERE task_name=%s",
            [telemetry_relay.RELAY],
        ).fetchall()
    assert len(rows) == 1 and rows[0][0] == "background"
    args = rows[0][1]
    assert args == {"kind": "metrics", "data": base64.b64encode(payload).decode()}
    assert "collector" not in json.dumps(args)
    post = AsyncMock(return_value=httpx.Response(200))
    post.return_value.request = httpx.Request("POST", settings.otel_metrics_endpoint)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    asyncio.run(telemetry_relay.export(None, **args))
    assert post.call_args.kwargs["content"] == payload
