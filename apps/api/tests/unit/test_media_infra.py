"""Validate the deployed media boundary, not a separate example configuration."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def test_media_compose_has_readonly_root_and_isolated_network() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose required to resolve includes/anchors")
    config = json.loads(
        subprocess.check_output(["docker", "compose", "config", "--format", "json"], cwd=ROOT)
    )
    media = config["services"]["worker-media"]
    assert media["read_only"] is True
    assert media["user"] == "10001:10001"
    assert media["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in media["security_opt"]
    assert media["pids_limit"] <= 256
    assert int(media["mem_limit"]) == 18 * 1024**3 and float(media["cpus"]) == 2
    assert media["tmpfs"][0].startswith("/scratch:rw,")
    assert {mount.split(":")[0] for mount in media["tmpfs"]} == {
        "/scratch",
        "/dev/shm",
        "/dev/mqueue",
    }
    assert all(":ro," in mount for mount in media["tmpfs"][1:])
    assert all(mount["read_only"] for mount in media["volumes"])
    assert set(media["networks"]) == {"media-data"}
    network = config["networks"]["media-data"]
    assert network["internal"] is True
    assert network["driver_opts"]["com.docker.network.bridge.gateway_mode_ipv4"] == "isolated"
    assert "media-data" not in config["services"]["api"]["networks"]
    for allowed in ("postgres", "storage"):
        assert "media-data" in config["services"][allowed]["networks"]
    assert media["environment"]["HTTP_PROXY"] == ""
    assert media["environment"]["HTTPS_PROXY"] == ""


def test_internal_services_wait_for_tcp_before_media_can_start() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose required")
    config = json.loads(
        subprocess.check_output(["docker", "compose", "config", "--format", "json"], cwd=ROOT)
    )
    postgres = config["services"]["postgres"]["healthcheck"]["test"][1]
    storage = config["services"]["storage"]["healthcheck"]["test"][1]
    # initdb's temporary server accepts Unix-socket queries before remote TCP.
    assert "pg_isready -h 127.0.0.1 " in postgres
    # Cluster readiness can precede the separate S3 listener startup.
    assert "nc -z 127.0.0.1 9000" in storage


def test_storage_listens_on_the_media_interface_as_well_as_default() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose required")
    config = json.loads(
        subprocess.check_output(["docker", "compose", "config", "--format", "json"], cwd=ROOT)
    )
    assert "-s3.ip.bind=0.0.0.0" in config["services"]["storage"]["command"]
