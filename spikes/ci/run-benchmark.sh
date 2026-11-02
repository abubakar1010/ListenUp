#!/usr/bin/env bash
# Runs one speech benchmark inside the container that .github/workflows/speech-benchmarks.yml
# starts with the stage 0 media process shape: 2 CPUs, OMP_NUM_THREADS=2, no swap (E4).
# Environment: BENCHMARK (b4-ami-manifest or b4), MODEL (B4's faster-whisper model),
# RESULTS (where numbers and text go), AUDIO_DIR (where fetched audio goes; never under
# RESULTS: the workflow caches it between runs and never uploads it).
set -euo pipefail

case "${BENCHMARK:-}" in
  b4-ami-manifest | b4) ;;
  *)
    echo "unknown benchmark: ${BENCHMARK:-}" >&2
    exit 2
    ;;
esac

results="${RESULTS:?set RESULTS}"
audio="${AUDIO_DIR:-/tmp/fillers}"
mkdir -p "$results"
bash ci/container-facts.sh "$results/container-facts.txt"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends ffmpeg curl ca-certificates git >/dev/null
pip install --quiet --root-user-action=ignore "uv==0.11.32"

case "$BENCHMARK" in
  b4-ami-manifest)
    # Text only: the annotation zip (checksum pinned) and SHA-256s of the 20 audio ranges.
    uv sync --frozen --python 3.12
    uv run --no-sync spike-ami manifest /tmp/ami_public_manual_1.6.2.zip \
      --out "$results/ami-windows.json"
    ;;
  b4)
    uv sync --frozen --python 3.12 --extra transcribe
    uv run --no-sync spike-ami fetch "$audio"
    uv run --no-sync spike-b4 "$audio" --model "${MODEL:-small.en}" --threads 2 \
      --out "$results" --evidence "CI-runner evidence (E4)"
    ;;
esac
