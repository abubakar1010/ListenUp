"""Which files a learner may upload (FR-CI-1, FR-CI-3, D5).

These checks run on what the browser declares, before any byte is sent. They keep
obvious mistakes out cheaply; the conversion job (#36) checks the real streams with
ffprobe, because a file name and a browser-reported type can lie (NFR-SEC-3).
"""

from dataclasses import dataclass

# Extension -> the MIME types browsers report for it. The first is the canonical one.
ACCEPTED_TYPES: dict[str, tuple[str, ...]] = {
    "mp3": ("audio/mpeg", "audio/mp3"),
    "m4a": ("audio/mp4", "audio/x-m4a", "audio/m4a"),
    "wav": ("audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"),
    "mp4": ("video/mp4", "audio/mp4"),
    "mov": ("video/quicktime",),
    "webm": ("video/webm", "audio/webm"),
}

ACCEPTED_NAMES = "MP3, M4A, WAV, MP4, MOV or WEBM"
MAX_TITLE_LENGTH = 300
MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True)
class FileProblem:
    code: str
    detail: str


def extension(filename: str) -> str:
    """The lower-case extension without the dot, or '' when there is none."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name.strip("."):
        return ""
    return name.rsplit(".", 1)[-1].lower()


def format_size(size: int) -> str:
    """Bytes as the learner reads them: '184 MB', '4.2 GB' (binary units)."""
    mb = size / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    if mb >= 10:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def check_file(filename: str, content_type: str, size: int, max_bytes: int) -> FileProblem | None:
    """Why this declared file cannot be uploaded, or None when it may be."""
    allowed = ACCEPTED_TYPES.get(extension(filename))
    mime = content_type.split(";", 1)[0].strip().lower()
    if allowed is None or mime not in allowed:
        return FileProblem(
            "unsupported_file_type",
            f"{filename} can't be used. Choose an {ACCEPTED_NAMES} file.",
        )
    if size > max_bytes:
        return FileProblem(
            "file_too_large",
            f"{filename} is {format_size(size)}. The limit is {format_size(max_bytes)} per "
            "file. Cut the part you want to practise, then upload that.",
        )
    return None


def normalized_type(content_type: str) -> str:
    """The MIME type without parameters, in lower case, as the upload is signed with."""
    return content_type.split(";", 1)[0].strip().lower()


def default_title(filename: str) -> str:
    """A content title from the file name: no folders, no extension, at most 300 characters."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    ext = extension(name)
    stem = name[: -(len(ext) + 1)] if ext else name
    title = " ".join(stem.split()) or name.strip() or "Untitled clip"
    return title[:MAX_TITLE_LENGTH]
