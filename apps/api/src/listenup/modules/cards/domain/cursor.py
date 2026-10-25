"""Opaque keyset cursors for the library list (Database Design 11.2, System Design 8.2).

A cursor names the last item of a page by (created_at, id); the next page starts
strictly after it in newest-first order. Clients treat it as an opaque string.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    id: uuid.UUID


class InvalidCursor(ValueError):
    pass


def encode(cursor: Cursor) -> str:
    raw = f"{cursor.created_at.isoformat()}|{cursor.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(value: str) -> Cursor:
    try:
        padded = value + "=" * (-len(value) % 4)
        created_at, item_id = base64.urlsafe_b64decode(padded).decode().split("|")
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            raise ValueError("cursor time has no zone")
        return Cursor(parsed, uuid.UUID(item_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as error:
        raise InvalidCursor(str(error)) from error
