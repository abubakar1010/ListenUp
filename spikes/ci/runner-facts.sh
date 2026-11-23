#!/usr/bin/env bash
# Records the facts exception E4 requires with every speech-benchmark run (#119):
# lscpu, nproc, free -b, uname -m, the runner image version and the commit SHA.
# Usage: runner-facts.sh OUT_FILE
set -euo pipefail

out="${1:?usage: runner-facts.sh OUT_FILE}"
mkdir -p "$(dirname "$out")"
{
  echo "# CI-runner evidence (E4)"
  echo
  echo "## lscpu"
  lscpu
  echo
  echo "## nproc"
  nproc
  echo
  echo "## free -b"
  free -b
  echo
  echo "## uname -m"
  uname -m
  echo
  echo "## runner image"
  echo "${ImageOS:-unknown} ${ImageVersion:-unknown}"
  echo
  echo "## commit"
  echo "${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
} >"$out"
