#!/usr/bin/env bash
# Fails if a benchmark's results folder holds anything but numbers and text. The folder
# becomes a public artifact, so this is an allowlist: audio in any format, archives and
# arrays are refused because they are not on it.
# Usage: check-results.sh RESULTS_DIR
set -euo pipefail

dir="${1:?usage: check-results.sh RESULTS_DIR}"
refused=$(find "$dir" -type f ! \( -name '*.json' -o -name '*.md' -o -name '*.txt' -o -name '*.csv' \))
if [ -n "$refused" ]; then
  echo "not uploading; only .json, .md, .txt and .csv may leave the job:"
  echo "$refused"
  exit 1
fi
