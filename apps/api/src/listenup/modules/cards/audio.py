"""AAC encoding owned by Cards, inside the existing media-job sandbox."""

import asyncio
from pathlib import Path


async def cut(source: Path, target: Path, start: int, end: int) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-ss",
        str(start / 1000),
        "-t",
        str((end - start) / 1000),
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-ac",
        "1",
        "-b:a",
        "64k",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(target),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        raise ValueError("The source audio could not be decoded.")
