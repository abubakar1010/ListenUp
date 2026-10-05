"""The export archive's rules: which files may go in, and how values become JSON (#92)."""

import datetime as dt
import ipaddress
import uuid
from dataclasses import dataclass
from decimal import Decimal

import pytest

from listenup.modules.export.domain import archive

LEARNER = uuid.UUID("01900000-0000-7000-8000-000000000001")
OTHER = uuid.UUID("01900000-0000-7000-8000-000000000002")


def test_archive_key_and_download_name() -> None:
    export = uuid.UUID("01900000-0000-7000-8000-0000000000aa")
    assert archive.archive_key(LEARNER, export) == f"users/{LEARNER}/exports/{export}.zip"
    ready = dt.datetime(2026, 10, 4, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-2)))
    assert archive.download_name(ready) == "listenup-export-2026-10-05.zip"
    assert archive.expires_at(ready, 7) == ready + dt.timedelta(days=7)


@pytest.mark.parametrize(
    ("key", "path", "allowed"),
    [
        (f"users/{LEARNER}/media/m/playback.mp4", "media/m/playback.mp4", True),
        (f"users/{OTHER}/media/m/playback.mp4", "media/m/playback.mp4", False),
        ("media/youtube/abc/playback.mp4", "media/abc/playback.mp4", False),
        (f"users/{LEARNER}/../{OTHER}/x.mp4", "media/x.mp4", False),
        (f"users/{LEARNER}/media/m/playback.mp4", "../escape.mp4", False),
        (f"users/{LEARNER}/media/m/playback.mp4", "/abs.mp4", False),
        (f"users/{LEARNER}/media/m/playback.mp4", "data.json", False),
        (f"users/{LEARNER}/media/m/playback.mp4", "media//x.mp4", False),
    ],
)
def test_only_the_learners_own_files_go_in(key: str, path: str, allowed: bool) -> None:
    assert archive.file_allowed(key, path, LEARNER) is allowed


@dataclass
class FakeRange:
    lower: int | None
    upper: int | None
    bounds: str = "[)"


def test_database_values_become_json() -> None:
    when = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.UTC)
    assert archive.json_value(LEARNER) == str(LEARNER)
    assert archive.json_value(when) == "2026-10-04T12:00:00+00:00"
    assert archive.json_value(Decimal("87.50")) == 87.5
    assert archive.json_value(ipaddress.ip_address("192.0.2.1")) == "192.0.2.1"
    assert archive.json_value(FakeRange(0, 60_000)) == {
        "lower": 0,
        "upper": 60_000,
        "bounds": "[)",
    }
    assert archive.json_value({"words": [{"at": when}]}) == {
        "words": [{"at": "2026-10-04T12:00:00+00:00"}]
    }
    assert archive.json_value("lower") == "lower"
    assert archive.json_value(b"\x01\xff") == "01ff"
    assert archive.json_value(dt.timedelta(seconds=90)) == 90.0


def test_document_lists_tables_files_and_omitted_columns() -> None:
    export = uuid.uuid4()
    when = dt.datetime(2026, 10, 4, tzinfo=dt.UTC)
    doc = archive.document(
        LEARNER,
        export,
        when,
        [
            archive.TableData("identity.users", [{"id": LEARNER}], ("password_hash",)),
            archive.TableData("content.contents", [], ()),
        ],
        [archive.FileEntry("media/m/playback.mp4", 10, "ab")],
        ["uploads/u.mp3"],
    )
    assert doc["format"] == "listenup-export"
    assert doc["tables"] == {"identity.users": [{"id": str(LEARNER)}], "content.contents": []}
    assert doc["omitted_columns"] == {"identity.users": ["password_hash"]}
    assert doc["files"] == [{"path": "media/m/playback.mp4", "size_bytes": 10, "sha256": "ab"}]
    assert doc["missing_files"] == ["uploads/u.mp3"]
    assert "YouTube media files are not included" in doc["notes"]


def test_a_table_exported_twice_is_a_bug() -> None:
    table = archive.TableData("content.contents", [], ())
    with pytest.raises(ValueError, match="twice"):
        archive.document(LEARNER, uuid.uuid4(), dt.datetime.now(dt.UTC), [table, table], [])
