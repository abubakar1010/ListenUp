"""Runs inside the actual Compose media service; invoked by check-media-sandbox.py."""

import asyncio
import errno
import json
import os
import socket
import sys
from pathlib import Path

from listenup.modules.content.scanner import ClamAV
from listenup.platform.errors import ProblemError
from listenup.platform.media_sandbox import MediaProcessFailed, run_process


def check_filesystem() -> None:
    assert os.getuid() == 10001, "media must be non-root"
    for folder in ("/tmp", "/app", "/models", "/signatures"):
        try:
            (Path(folder) / "listenup-sandbox-probe").write_text("must fail")
        except OSError as error:
            assert error.errno in (errno.EROFS, errno.EACCES), (folder, error)
        else:
            raise AssertionError(f"write outside scratch succeeded: {folder}")
    path = Path("/scratch/probe")
    path.write_text("scratch works")
    path.unlink()
    print(
        "PASS non-root, read-only root/models/signatures, writable scratch", flush=True
    )


def check_network() -> None:
    for host, port in (("postgres", 5432), ("storage", 9000)):
        try:
            with socket.create_connection((host, port), timeout=3):
                pass
        except OSError as error:
            raise AssertionError(
                f"required service is not reachable: {host}:{port}"
            ) from error
    for host in ["api", *json.loads(os.environ["SANDBOX_API_ADDRESSES"])]:
        try:
            connection = socket.create_connection((host, 8000), timeout=1)
        except OSError:
            continue
        connection.close()
        raise AssertionError(f"media reached the API at {host}")
    print(
        "PASS storage/database reachable; API DNS, IPs and host gateway refused",
        flush=True,
    )


async def check_scanner() -> None:
    eicar = Path("/scratch/eicar")
    eicar.write_bytes(
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    clean = Path("/scratch/clean")
    clean.write_text("a harmless clean file")
    # The tiny hash database intentionally has no CVD age. Verify production
    # refuses it, then test engine results with only the fixture's age check off.
    try:
        await ClamAV().scan(clean)
    except ProblemError as error:
        assert error.code == "upload_unreadable"
    else:
        raise AssertionError("production accepted databases without a fresh CVD")
    fixture_scanner = ClamAV(signature_max_age_days=None)
    await fixture_scanner.scan(clean)
    for path, code in (
        (eicar, "upload_infected"),
        (Path("/scratch/missing"), "upload_unreadable"),
    ):
        try:
            await fixture_scanner.scan(path)
        except ProblemError as error:
            assert error.code == code, (error.code, code)
        else:
            raise AssertionError(f"scanner accepted {path}")
    oversized = Path("/scratch/oversized")
    oversized.write_bytes(b"a" * 2048)
    try:
        await ClamAV(signature_max_age_days=None, max_file_bytes=64).scan(oversized)
    except ProblemError as error:
        assert error.code == "upload_infected"
    else:
        raise AssertionError("ClamAV silently accepted a partial scan")
    print(
        "PASS real ClamAV: EICAR refused, clean accepted, unreadable refused",
        flush=True,
    )


async def check_limits() -> None:
    for kind, code, seconds, cpu in (
        ("time", "import time; time.sleep(30)", 0.5, 5),
        ("memory", "x = bytearray(512 * 1024 * 1024)", 5, 5),
        ("CPU", "while True: pass", 5, 1),
    ):
        try:
            await run_process(
                [sys.executable, "-c", code],
                b"",
                seconds=seconds,
                memory_mb=128,
                cpu_seconds=cpu,
            )
        except MediaProcessFailed:
            pass
        else:
            raise AssertionError(f"{kind} limit was not enforced")
    print("PASS real subprocesses killed at time, memory and CPU limits", flush=True)


async def main() -> None:
    check_filesystem()
    check_network()
    await check_scanner()
    await check_limits()


if __name__ == "__main__":
    asyncio.run(main())
