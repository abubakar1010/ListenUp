"""Fail-closed upload scanning before any media parser (NFR-SEC-3, ADR 0049)."""

import asyncio
import contextlib
from pathlib import Path
from typing import Protocol

from listenup.platform.config import get_settings
from listenup.platform.errors import ProblemError


class Scanner(Protocol):
    async def scan(self, source: Path) -> None:
        """Return only for a clean file; refuse with a stable ProblemError code."""
        ...


class ClamAV:
    def __init__(
        self, *, signature_max_age_days: int | None = 7, max_file_bytes: int | None = None
    ) -> None:
        # A custom hash-only test database has no CVD timestamp. Production's
        # default always requires fresh official databases; there is no env toggle.
        self.signature_max_age_days = signature_max_age_days
        self.max_file_bytes = max_file_bytes or get_settings().upload_max_bytes

    async def scan(self, source: Path) -> None:
        age = (
            [f"--fail-if-cvd-older-than={self.signature_max_age_days}"]
            if self.signature_max_age_days is not None
            else []
        )
        try:
            process = await asyncio.create_subprocess_exec(
                "clamscan",
                "--database=/signatures",
                "--no-summary",
                "--alert-exceeds-max=yes",
                f"--max-filesize={self.max_file_bytes}",
                f"--max-scansize={self.max_file_bytes * 2}",
                *age,
                str(source),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as error:
            raise ProblemError(
                422, "upload_unreadable", "This file could not be scanned safely."
            ) from error
        try:
            await process.communicate()
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if process.returncode == 1:
            raise ProblemError(
                422,
                "upload_infected",
                "This file was rejected by the malware scanner. Upload a clean file.",
            )
        if process.returncode != 0:
            raise ProblemError(422, "upload_unreadable", "This file could not be scanned safely.")


_scanner: Scanner | None = None


def get_scanner() -> Scanner:
    return _scanner if _scanner is not None else ClamAV()


def use_scanner(value: Scanner | None) -> None:
    """Replace the boundary in tests; production always defaults to ClamAV."""
    global _scanner
    _scanner = value
