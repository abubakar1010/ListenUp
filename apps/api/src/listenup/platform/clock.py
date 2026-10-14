"""The API's UTC wall clock, shared by routes that need server-time decisions."""

from datetime import UTC, datetime


def server_now() -> datetime:
    return datetime.now(UTC)
