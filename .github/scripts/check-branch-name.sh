#!/usr/bin/env bash
set -euo pipefail

branch_name="${1:-}"

if [[ -z "$branch_name" ]]; then
  echo "error: pass the branch name as the first argument" >&2
  exit 2
fi

# Permanent integration branches are not working branches.
case "$branch_name" in
  main | master | develop)
    exit 0
    ;;
esac

allowed_types='feat|fix|docs|refactor|perf|test|build|ci|chore|revert|hotfix|release'
if [[ ! "$branch_name" =~ ^(${allowed_types})/([a-z0-9]+(-[a-z0-9]+)+)$ ]]; then
  cat >&2 <<EOF
error: branch '$branch_name' is not readable and auditable

Use: <type>/<readable-kebab-purpose>
Types: feat, fix, docs, refactor, perf, test, build, ci, chore, revert,
       hotfix, release
Examples: fix/142-login-timeout, feat/lu-87-shadow-feedback,
          docs/branch-naming-policy

The purpose must contain at least two lowercase words. Tool names, session IDs,
UUIDs, hashes, and generated random names are not valid branch identities.
EOF
  exit 1
fi

purpose="${branch_name#*/}"
if [[ ! "$purpose" =~ [a-z] ]]; then
  echo "error: branch purpose must contain meaningful words" >&2
  exit 1
fi

if [[ "$purpose" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] \
  || { [[ ${#purpose} -ge 12 ]] && [[ "$purpose" =~ ^[0-9a-f-]+$ ]]; }; then
  echo "error: branch purpose must not be a UUID or hash" >&2
  exit 1
fi
