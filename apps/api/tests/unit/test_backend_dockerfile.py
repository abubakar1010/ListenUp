"""The speech image builds on arm64 without a compiler in the runtime image (#232; ADR 0073).

praat-parselmouth 0.4.7 has no Linux arm64 wheel, so a build there compiles it. The
compiler lives in a throwaway stage that makes a wheel; the worker-media image installs
that wheel and never sees the toolchain. These read the Dockerfile as data, so they run
anywhere; the real arm64 build runs in the Deploy check and in the Release workflow.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TEXT = (REPO / "infra/docker/backend.Dockerfile").read_text()
LOCK = tomllib.loads((REPO / "apps/api/uv.lock").read_text())
COMPILER = re.compile(r"\b(build-essential|g\+\+|gcc|cmake|make|ninja-build)\b")


def stages() -> dict[str, dict[str, str]]:
    """Stage name -> its base and its instructions with continuation lines joined."""
    found: dict[str, dict[str, str]] = {}
    current = ""
    for line in TEXT.replace("\\\n", " ").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = re.match(r"FROM\s+(?:--platform=\S+\s+)?(\S+)\s+AS\s+(\S+)", line)
        if match:
            current = match.group(2)
            found[current] = {"base": match.group(1), "body": ""}
        elif current:
            found[current]["body"] += line + "\n"
    return found


def chain(stage: str) -> list[str]:
    """The stage and every stage it builds on, nearest first."""
    result = [stage]
    while stages()[result[-1]]["base"] in stages():
        result.append(stages()[result[-1]]["base"])
    return result


def locked_version(name: str) -> str:
    return next(p["version"] for p in LOCK["package"] if p["name"] == name)


def test_a_throwaway_stage_compiles_parselmouth_at_the_locked_version() -> None:
    stage = stages()["parselmouth-wheel"]
    assert COMPILER.search(stage["body"]), "the wheel stage needs a C++ toolchain and CMake"
    assert "cmake" in stage["body"] and (
        "g++" in stage["body"] or "build-essential" in stage["body"]
    )
    assert "pip wheel" in stage["body"]
    assert "--no-deps" in stage["body"]
    pinned = re.search(r"ARG PARSELMOUTH_VERSION=(\S+)", stage["body"])
    assert pinned and pinned.group(1) == locked_version("praat-parselmouth")


def test_no_runtime_image_contains_a_compiler() -> None:
    for runtime in ("api", "worker", "worker-media", "signature-update", "backup"):
        for name in chain(runtime):
            assert not COMPILER.search(stages()[name]["body"]), (runtime, name)


def test_the_speech_image_installs_the_prebuilt_wheel_instead_of_building_the_sdist() -> None:
    body = stages()["worker-media"]["body"]
    assert "--no-install-package praat-parselmouth" in body
    assert "from=parselmouth-wheel" in body
    install = re.search(r"uv pip install[^&;]*--no-deps[^&;]*\.whl", body)
    assert install, "the wheel is installed from disk with no index and no dependencies"
    assert "--index" not in install.group(0)
    assert "parselmouth-wheel" not in {stages()[n]["base"] for n in stages()}
