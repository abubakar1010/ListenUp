"""Carry content-free OTLP through PostgreSQL; only the default pool exports it.

No collector address or authentication header is accepted from a media job.
Existing queue retries provide bounded delivery without opening the media network.
"""

import base64
from typing import Literal

import httpx
import procrastinate

from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job

RELAY = "platform.export_media_telemetry"
MAX_BATCH_BYTES = 1024 * 1024


def submit(kind: Literal["traces", "metrics"], data: bytes) -> None:
    """Called from SDK exporter threads, with a separate short-lived DB pool."""
    if len(data) > MAX_BATCH_BYTES:
        raise ValueError("media telemetry batch exceeds its limit")
    relay = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=get_settings().database_url)
    )
    with relay.open():
        relay.configure_task(name=RELAY, queue=Lane.BACKGROUND.value).defer(
            kind=kind, data=base64.b64encode(data).decode("ascii")
        )


@job(Lane.BACKGROUND, RELAY)
async def export(deps: JobDeps, *, kind: str, data: str) -> None:
    settings = get_settings()
    if not settings.otel_enabled:
        return
    if kind not in ("traces", "metrics") or len(data) > MAX_BATCH_BYTES * 2:
        raise PermanentError("invalid media telemetry batch")
    try:
        payload = base64.b64decode(data, validate=True)
    except ValueError as error:
        raise PermanentError("invalid media telemetry encoding") from error
    if len(payload) > MAX_BATCH_BYTES:
        raise PermanentError("media telemetry batch exceeds its limit")
    endpoint = settings.otel_traces_endpoint if kind == "traces" else settings.otel_metrics_endpoint
    if endpoint is None:
        return
    from listenup.platform.telemetry import _parse_headers

    headers = _parse_headers(
        settings.otel_headers.get_secret_value() if settings.otel_headers else None
    )
    headers["Content-Type"] = "application/x-protobuf"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(endpoint, content=payload, headers=headers)
        response.raise_for_status()
