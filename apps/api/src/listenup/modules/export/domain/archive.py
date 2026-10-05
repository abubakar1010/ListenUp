"""The export archive: its layout, its JSON and how long it is kept (#92, ADR 0030).

Pure rules, no I/O. The build job collects each module's rows and files and hands
them here to be checked and written down.

The archive is one ZIP file:

    data.json                      every learner table's rows, and a list of the files
    media/<media id>/playback.mp4  the playback file of each clip the learner uploaded
    uploads/<upload id>.<ext>      originals of uploads that were not converted yet

YouTube media files are never included, even for the learner's own YouTube items
(D10); the items themselves (link, title, passages) are in data.json.
"""

import datetime as dt
import ipaddress
import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

FORMAT = "listenup-export"
FORMAT_VERSION = 1
DATA_FILE = "data.json"

NOTES = (
    "This archive holds a copy of your ListenUp data on the date above. "
    "YouTube media files are not included; your YouTube clips' links, titles and "
    "practice are. Password hashes, sign-in cookie hashes and internal storage "
    "locations are left out."
)


def archive_key(learner: uuid.UUID, export_id: uuid.UUID) -> str:
    """Where the archive is stored: under the learner's own prefix (Architecture 8.1)."""
    return f"users/{learner}/exports/{export_id}.zip"


def download_name(ready_at: dt.datetime) -> str:
    return f"listenup-export-{ready_at.astimezone(dt.UTC):%Y-%m-%d}.zip"


def expires_at(ready_at: dt.datetime, keep_days: int) -> dt.datetime:
    """When a finished archive is deleted (`LISTENUP_EXPORT_KEEP_DAYS`, ADR 0030)."""
    return ready_at + dt.timedelta(days=keep_days)


def file_allowed(key: str, path: str, learner: uuid.UUID) -> bool:
    """A file may go into the learner's archive only from their own storage prefix,
    to a plain relative path inside the archive."""
    if not key.startswith(f"users/{learner}/") or ".." in key.split("/"):
        return False
    parts = path.split("/")
    return (
        bool(path)
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in ("", ".", "..") for part in parts)
        and path != DATA_FILE
    )


def json_value(value: Any) -> Any:
    """A database value as JSON: ids and times as text, ranges as their bounds."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(
        value,
        ipaddress.IPv4Address
        | ipaddress.IPv6Address
        | ipaddress.IPv4Network
        | ipaddress.IPv6Network
        | ipaddress.IPv4Interface
        | ipaddress.IPv6Interface,
    ):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, Mapping):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [json_value(v) for v in value]
    if hasattr(value, "lower") and hasattr(value, "upper") and hasattr(value, "bounds"):
        # A PostgreSQL range (psycopg's or SQLAlchemy's): [lower, upper) and so on.
        return {
            "lower": json_value(value.lower),
            "upper": json_value(value.upper),
            "bounds": str(value.bounds),
        }
    return str(value)


@dataclass(frozen=True)
class TableData:
    name: str
    rows: list[dict[str, Any]]
    omitted: tuple[str, ...]


@dataclass(frozen=True)
class FileEntry:
    path: str
    size_bytes: int
    sha256: str


def document(
    learner: uuid.UUID,
    export_id: uuid.UUID,
    exported_at: dt.datetime,
    tables: Iterable[TableData],
    files: Iterable[FileEntry],
    missing: Iterable[str] = (),
) -> dict[str, Any]:
    """The contents of data.json."""
    table_list = list(tables)
    names = [table.name for table in table_list]
    duplicated = {name for name in names if names.count(name) > 1}
    if duplicated:
        raise ValueError(f"tables exported twice: {sorted(duplicated)}")
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "export_id": str(export_id),
        "user_id": str(learner),
        "exported_at": exported_at.isoformat(),
        "notes": NOTES,
        "tables": {
            table.name: [{k: json_value(v) for k, v in row.items()} for row in table.rows]
            for table in table_list
        },
        "omitted_columns": {
            table.name: list(table.omitted) for table in table_list if table.omitted
        },
        "files": [
            {"path": entry.path, "size_bytes": entry.size_bytes, "sha256": entry.sha256}
            for entry in files
        ],
        # Files a row names but storage no longer had when the archive was built.
        "missing_files": list(missing),
    }
