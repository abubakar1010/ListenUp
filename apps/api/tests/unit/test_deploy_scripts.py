"""The host deploy and rollback scripts (#112, Architecture 11).

Each test runs the real scripts against a throwaway deploy directory with a fake
`docker` first on the PATH. The fake records every call with the image tag it saw
and fails on demand, so the order of the steps and what a failure stops are visible.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DEPLOY = REPO / "infra/deploy/deploy.sh"
ROLLBACK = REPO / "infra/deploy/rollback.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "${LISTENUP_IMAGE_TAG:-<none>} $*" >> "$FAKE_DOCKER_LOG"
if [[ -n "${FAKE_DOCKER_FAIL:-}" && "$*" == *"$FAKE_DOCKER_FAIL"* ]]; then
  if [[ -z "${FAKE_DOCKER_FAIL_TAG:-}" || "$FAKE_DOCKER_FAIL_TAG" == "$LISTENUP_IMAGE_TAG" ]]; then
    exit 3
  fi
fi
exit 0
"""


@dataclass
class Host:
    root: Path
    env: dict[str, str]
    log: Path

    def run(self, script: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), *args],
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def state(self, name: str) -> str | None:
        path = self.root / "state" / name
        return path.read_text().strip() if path.exists() else None

    def set_state(self, name: str, value: str) -> None:
        (self.root / "state").mkdir(exist_ok=True)
        (self.root / "state" / name).write_text(value + "\n")


@pytest.fixture
def host(tmp_path: Path) -> Host:
    root = tmp_path / "listenup"
    root.mkdir()
    (root / "compose.prod.yml").write_text("services: {}\n")
    (root / ".env").write_text("LISTENUP_DOMAIN=example.test\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "LISTENUP_DEPLOY_DIR": str(root),
        "FAKE_DOCKER_LOG": str(log),
    }
    return Host(root, env, log)


def compose(host: Host, tag: str, rest: str) -> str:
    return (
        f"{tag} compose --project-name listenup --env-file {host.root}/.env "
        f"--file {host.root}/compose.prod.yml {rest}"
    )


def test_a_deploy_pulls_checks_the_bucket_migrates_and_only_then_restarts(host: Host) -> None:
    result = host.run(DEPLOY, "sha-0123456789ab")

    assert result.returncode == 0, result.stderr
    assert host.calls() == [
        compose(host, "sha-0123456789ab", "pull --quiet"),
        compose(host, "sha-0123456789ab", "run --rm --no-deps storage-check"),
        compose(host, "sha-0123456789ab", "run --rm --no-deps migrate"),
        compose(host, "sha-0123456789ab", "up --detach --wait --remove-orphans"),
    ]


def test_a_failed_migration_leaves_the_running_release_untouched(host: Host) -> None:
    host.set_state("current-tag", "r6")

    result = host.run(DEPLOY, "r7", FAKE_DOCKER_FAIL="run --rm --no-deps migrate")

    assert result.returncode != 0
    assert not any(" up " in call for call in host.calls())
    assert "migrations failed" in result.stderr
    assert host.state("current-tag") == "r6"
    assert host.state("previous-tag") is None


def test_a_public_bucket_stops_the_deploy_before_migrations(host: Host) -> None:
    result = host.run(DEPLOY, "r7", FAKE_DOCKER_FAIL="storage-check")

    assert result.returncode != 0
    assert "storage check" in result.stderr
    assert not any("migrate" in call or " up " in call for call in host.calls())


def test_a_failed_pull_stops_everything(host: Host) -> None:
    result = host.run(DEPLOY, "r7", FAKE_DOCKER_FAIL="pull")

    assert result.returncode != 0
    assert len(host.calls()) == 1


def test_a_successful_deploy_records_the_release(host: Host) -> None:
    host.set_state("current-tag", "r6")

    assert host.run(DEPLOY, "r7").returncode == 0

    assert host.state("current-tag") == "r7"
    assert host.state("previous-tag") == "r6"
    [line] = (host.root / "state/releases.log").read_text().splitlines()
    assert line.endswith(" deploy r7 previous=r6")


def test_the_first_deploy_has_no_previous_release(host: Host) -> None:
    assert host.run(DEPLOY, "r1").returncode == 0

    assert host.state("current-tag") == "r1"
    assert host.state("previous-tag") is None


def test_redeploying_the_same_tag_keeps_the_real_previous_release(host: Host) -> None:
    host.set_state("current-tag", "r7")
    host.set_state("previous-tag", "r6")

    assert host.run(DEPLOY, "r7").returncode == 0

    assert host.state("previous-tag") == "r6"


def test_a_release_that_never_gets_healthy_is_replaced_by_the_running_one(host: Host) -> None:
    host.set_state("current-tag", "r6")

    result = host.run(DEPLOY, "r7", FAKE_DOCKER_FAIL=" up ", FAKE_DOCKER_FAIL_TAG="r7")

    assert result.returncode != 0
    assert host.calls()[-1] == compose(host, "r6", "up --detach --wait --remove-orphans")
    assert not any(call.startswith("r6 ") and "migrate" in call for call in host.calls())
    assert host.state("current-tag") == "r6"
    assert "restored r6" in result.stderr


@pytest.mark.parametrize("tag", ["", "latest", "r7;reboot", "../r7", "sha-XYZ", "R7"])
def test_a_tag_that_is_not_an_immutable_release_is_refused_before_docker_runs(
    host: Host, tag: str
) -> None:
    result = host.run(DEPLOY, tag)

    assert result.returncode == 2
    assert host.calls() == []


def test_a_missing_environment_file_is_refused(host: Host) -> None:
    (host.root / ".env").unlink()

    result = host.run(DEPLOY, "r7")

    assert result.returncode == 2
    assert ".env" in result.stderr
    assert host.calls() == []


def test_rollback_redeploys_the_previous_image_without_migrations(host: Host) -> None:
    host.set_state("current-tag", "r7")
    host.set_state("previous-tag", "r6")

    result = host.run(ROLLBACK)

    assert result.returncode == 0, result.stderr
    assert host.calls() == [
        compose(host, "r6", "pull --quiet"),
        compose(host, "r6", "up --detach --wait --remove-orphans"),
    ]
    assert host.state("current-tag") == "r6"
    assert host.state("previous-tag") == "r7"
    lines = (host.root / "state/releases.log").read_text().splitlines()
    assert lines[-1].endswith(" rollback r6 previous=r7")


def test_rollback_to_a_named_release(host: Host) -> None:
    host.set_state("current-tag", "r7")
    host.set_state("previous-tag", "r6")

    assert host.run(ROLLBACK, "r4").returncode == 0

    assert host.state("current-tag") == "r4"
    assert host.calls()[-1] == compose(host, "r4", "up --detach --wait --remove-orphans")


def test_rollback_without_a_previous_release_is_refused(host: Host) -> None:
    host.set_state("current-tag", "r1")

    result = host.run(ROLLBACK)

    assert result.returncode == 2
    assert "no previous release" in result.stderr
    assert host.calls() == []
