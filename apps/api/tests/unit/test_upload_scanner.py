from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from listenup.modules.content import scanner
from listenup.platform.errors import ProblemError


@pytest.mark.anyio
@pytest.mark.parametrize("exit_code,code", [(1, "upload_infected"), (2, "upload_unreadable")])
async def test_clamav_refuses_infected_or_unreadable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, code: str
) -> None:
    process = AsyncMock()
    process.returncode = exit_code
    process.communicate.return_value = (b"", b"")
    monkeypatch.setattr(scanner.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(ProblemError) as refused:
        await scanner.ClamAV().scan(tmp_path / "source")
    assert refused.value.code == code


@pytest.mark.anyio
@pytest.mark.parametrize("age", [7, None])
async def test_clamav_accepts_only_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age: int | None
) -> None:
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"", b"")
    monkeypatch.setattr(scanner.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    await scanner.ClamAV(signature_max_age_days=age).scan(tmp_path / "source")
    command = scanner.asyncio.create_subprocess_exec.call_args.args
    assert ("--fail-if-cvd-older-than=7" in command) is (age == 7)


@pytest.mark.anyio
async def test_scanner_missing_binary_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scanner.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
    )
    with pytest.raises(ProblemError) as refused:
        await scanner.ClamAV().scan(Path("/missing"))
    assert refused.value.code == "upload_unreadable"


@pytest.mark.anyio
async def test_scanner_cancellation_kills_and_reaps_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    process = AsyncMock()
    process.returncode = None
    process.kill = Mock()
    process.communicate.side_effect = scanner.asyncio.CancelledError
    monkeypatch.setattr(scanner.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(scanner.asyncio.CancelledError):
        await scanner.ClamAV().scan(Path("/source"))
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


def test_scanner_boundary_can_be_replaced_and_restored() -> None:
    fake = AsyncMock()
    scanner.use_scanner(fake)
    assert scanner.get_scanner() is fake
    scanner.use_scanner(None)
    assert isinstance(scanner.get_scanner(), scanner.ClamAV)


@pytest.mark.anyio
async def test_scan_limits_are_refusals_not_silent_partial_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = AsyncMock()
    process.returncode = 1
    process.communicate.return_value = (b"", b"")
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(scanner.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ProblemError) as refused:
        await scanner.ClamAV(max_file_bytes=64).scan(Path("/source"))
    assert refused.value.code == "upload_infected"
    assert "--alert-exceeds-max=yes" in spawn.call_args.args
    assert "--max-filesize=64" in spawn.call_args.args
    assert "--max-scansize=128" in spawn.call_args.args
