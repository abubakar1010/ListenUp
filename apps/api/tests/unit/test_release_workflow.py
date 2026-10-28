"""The release workflow publishes multi-arch images (#231; ADR 0070 and 0066).

The stage 0 host may be an Arm VM, and an amd64-only image fails there with
`exec format error`. These read the workflows as data, so they run anywhere; the real
build runs in the Deploy check (arm64 on a native runner) and in the Release workflow.
"""

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[4]
RELEASE = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())
DEPLOY_CHECK = yaml.safe_load((REPO / ".github/workflows/deploy-check.yml").read_text())

IMAGES: list[dict[str, Any]] = RELEASE["jobs"]["images"]["strategy"]["matrix"]["include"]
STEPS: list[dict[str, Any]] = RELEASE["jobs"]["images"]["steps"]

# Images published for amd64 only. Empty since praat-parselmouth builds on arm64 in a
# throwaway stage (#232); add an image here only with a reason and an issue.
AMD64_ONLY: set[str] = set()


def platforms(entry: dict[str, Any]) -> set[str]:
    return set(str(entry["platforms"]).split(","))


def step(name: str) -> dict[str, Any]:
    return next(s for s in STEPS if s.get("name") == name or s.get("uses", "").startswith(name))


def test_every_image_declares_platforms_and_always_includes_amd64() -> None:
    assert {e["image"] for e in IMAGES} == {
        "api", "worker", "worker-media", "backup", "signature-update", "edge",
    }  # fmt: skip
    for entry in IMAGES:
        assert "linux/amd64" in platforms(entry), entry["image"]


def test_arm64_is_published_for_every_image_except_the_documented_exception() -> None:
    for entry in IMAGES:
        expected = entry["image"] not in AMD64_ONLY
        assert ("linux/arm64" in platforms(entry)) is expected, entry["image"]


def test_the_build_uses_the_matrix_platforms_after_emulation_is_set_up() -> None:
    uses = [s.get("uses", "") for s in STEPS]
    qemu = next(i for i, u in enumerate(uses) if u.startswith("docker/setup-qemu-action@"))
    build = next(i for i, u in enumerate(uses) if u.startswith("docker/build-push-action@"))
    assert qemu < build
    assert STEPS[build]["with"]["platforms"] == "${{ matrix.platforms }}"


def test_tags_stay_immutable_and_never_include_latest() -> None:
    tags = STEPS[
        next(
            i
            for i, s in enumerate(STEPS)
            if s.get("uses", "").startswith("docker/build-push-action@")
        )
    ]["with"]["tags"]
    assert "latest" not in tags
    assert re.findall(r"outputs\.([a-z-]+)\s*}}\s*$", tags.strip().splitlines()[0]) == ["sha-tag"]
    assert re.findall(r"outputs\.([a-z-]+)\s*}}\s*$", tags.strip().splitlines()[1]) == [
        "release-tag"
    ]


def test_the_deploy_check_builds_every_arm64_release_image_on_a_native_arm_runner() -> None:
    job = DEPLOY_CHECK["jobs"]["arm64-images"]
    assert job["runs-on"] == "ubuntu-24.04-arm"
    built = {e["image"] for e in job["strategy"]["matrix"]["include"]}
    released = {e["image"] for e in IMAGES if "linux/arm64" in platforms(e)}
    assert built == released


def test_the_release_reuses_the_arm64_layers_the_deploy_check_caches() -> None:
    """Compiling praat-parselmouth under QEMU would otherwise run on every release."""
    build = next(s for s in STEPS if s.get("uses", "").startswith("docker/build-push-action@"))
    steps = DEPLOY_CHECK["jobs"]["arm64-images"]["steps"]
    built = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action@"))
    written = built["with"]["cache-to"]
    scope = re.search(r"scope=(.+)$", written)
    assert scope and scope.group(1) == "arm64-${{ matrix.image }}"
    assert f"type=gha,scope={scope.group(1)}" in build["with"]["cache-from"].splitlines()


def test_the_native_arm_job_runs_the_speech_runtime_check_on_worker_media() -> None:
    """Compiling Praat is not enough: the arm64 libraries must also behave like amd64."""
    steps = DEPLOY_CHECK["jobs"]["arm64-images"]["steps"]
    build = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action@"))
    assert build["with"]["load"] == "${{ matrix.image == 'worker-media' }}"
    smoke = next(s for s in steps if "check-speech-runtime.py" in s.get("run", ""))
    assert smoke["if"] == "matrix.image == 'worker-media'"
    assert (REPO / "infra/scripts/check-speech-runtime.py").is_file()
    assert build["with"]["tags"] == "listenup-${{ matrix.image }}:arm64-check"
    assert "listenup-worker-media:arm64-check" in smoke["run"]  # the image just loaded
