"""Opaque keyset cursors for the sessions list (Database Design 11.2, System Design 8.2).

A cursor names the last session of a page by (updated_at, id); the next page starts
strictly after it in most-recent-first order. Clients treat it as an opaque string.
The format matches the library's cursor (`content/domain/cursor.py`), which this
module may not import (Architecture 4.3).
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Cursor:
    updated_at: datetime
    id: uuid.UUID


class InvalidCursor(ValueError):
    pass


def encode(cursor: Cursor) -> str:
    raw = f"{cursor.updated_at.isoformat()}|{cursor.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(value: str) -> Cursor:
    try:
        padded = value + "=" * (-len(value) % 4)
        updated_at, session_id = base64.urlsafe_b64decode(padded).decode().split("|")
        parsed = datetime.fromisoformat(updated_at)
        if parsed.tzinfo is None:
            raise ValueError("cursor time has no zone")
        return Cursor(parsed, uuid.UUID(session_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise InvalidCursor(str(error)) from error
