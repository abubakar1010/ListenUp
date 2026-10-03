"""Which declared files may be uploaded (FR-CI-1, FR-CI-3, D5), and library cursors."""

import uuid
from datetime import UTC, datetime

import pytest

from listenup.modules.content.domain import cursor
from listenup.modules.content.domain.files import (
    check_file,
    default_title,
    extension,
    format_size,
)

MB = 1024 * 1024
LIMIT = 500 * MB


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("talk.mp3", "audio/mpeg"),
        ("talk.MP3", "audio/mp3"),
        ("voice memo.m4a", "audio/x-m4a"),
        ("clip.wav", "audio/wav"),
        ("scene.mp4", "video/mp4"),
        ("scene.mov", "video/quicktime"),
        ("scene.webm", "video/webm; codecs=vp9"),
    ],
)
def test_accepted_types_pass(filename: str, content_type: str) -> None:
    assert check_file(filename, content_type, 50 * MB, LIMIT) is None


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.pdf", "application/pdf"),
        ("movie.mkv", "video/x-matroska"),
        ("talk.mp3", "video/quicktime"),  # extension and type disagree
        ("talk", "audio/mpeg"),  # no extension
        ("talk.mp3", ""),
    ],
)
def test_other_types_are_refused(filename: str, content_type: str) -> None:
    problem = check_file(filename, content_type, MB, LIMIT)
    assert problem is not None
    assert problem.code == "unsupported_file_type"
    assert filename in problem.detail


def test_a_file_over_the_limit_is_refused_with_its_size() -> None:
    problem = check_file("talk.mp3", "audio/mpeg", LIMIT + 1, LIMIT)
    assert problem is not None
    assert problem.code == "file_too_large"
    assert "500 MB" in problem.detail
    assert check_file("talk.mp3", "audio/mpeg", LIMIT, LIMIT) is None


def test_type_is_checked_before_size() -> None:
    problem = check_file("movie.mkv", "video/x-matroska", 4 * 1024 * MB, LIMIT)
    assert problem is not None
    assert problem.code == "unsupported_file_type"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("a.mp3", "mp3"), ("a.b.WAV", "wav"), (".mp3", ""), ("noext", ""), ("dir/x.mov", "mov")],
)
def test_extension(filename: str, expected: str) -> None:
    assert extension(filename) == expected


def test_default_title_drops_folders_and_extension() -> None:
    assert default_title("C:\\clips\\street-trees  talk.mp4") == "street-trees talk"
    assert default_title("x" * 400 + ".mp3") == "x" * 300


def test_sizes_read_as_people_expect() -> None:
    assert format_size(184 * MB) == "184 MB"
    assert format_size(int(4.2 * 1024 * MB)) == "4.2 GB"
    assert format_size(MB // 2) == "0.5 MB"


def test_a_cursor_round_trips() -> None:
    original = cursor.Cursor(datetime(2026, 10, 3, 12, 0, 0, 123456, tzinfo=UTC), uuid.uuid4())
    assert cursor.decode(cursor.encode(original)) == original


@pytest.mark.parametrize("value", ["", "not-base64!", "Zm9v", "MjAyNi0xMC0wM3x4"])
def test_a_broken_cursor_is_refused(value: str) -> None:
    with pytest.raises(cursor.InvalidCursor):
        cursor.decode(value)
