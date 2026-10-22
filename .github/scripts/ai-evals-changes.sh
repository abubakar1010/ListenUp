#!/usr/bin/env bash
# Compare PR bases and push ranges, including deletes and both sides of renames.
set -euo pipefail
repo_root=$(git rev-parse --show-toplevel)
head_sha=${HEAD_SHA:-HEAD}
base_sha=${BASE_SHA:-}
if [[ -z "$base_sha" || "$base_sha" =~ ^0+$ ]]; then
  default_branch=${DEFAULT_BRANCH:-main}
  base_sha=$(git merge-base "$head_sha" "origin/$default_branch")
fi
if [[ ${EVENT_NAME:-push} == pull_request ]]; then
  base_sha=$(git merge-base "$base_sha" "$head_sha")
fi
git diff --no-renames --name-only -z "$base_sha" "$head_sha" |
  PYTHONPATH="$repo_root/apps/api/src" python3 -m listenup.ai.evals.paths
