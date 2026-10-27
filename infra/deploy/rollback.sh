#!/usr/bin/env bash
# Roll production back to the previous release (#112).
#
#   rollback.sh                    the release recorded in state/previous-tag
#   rollback.sh <tag>              the same, named (it must be the previous release)
#   rollback.sh --force <tag>      any earlier release still in the registry
#
# Only the images change: migrations are expand-only (Database Design 12.2), so the
# previous release's code runs on the newer schema and nothing is migrated backwards.
# Only the previous release is sure to: a contract step (a drop) may ship one release
# after the code stopped using what it drops, so an older release may need what is
# gone. --force is for when the releases in between dropped nothing that tag reads
# (check their migrations first). Afterwards state/previous-tag names the release
# rolled away from, so a second rollback returns to it. See docs/runbooks/deploy.md.
set -euo pipefail

dir="${LISTENUP_DEPLOY_DIR:-/opt/listenup}"
force=false
if [[ "${1:-}" == "--force" ]]; then
  force=true
  shift
fi
previous="$(cat "$dir/state/previous-tag" 2>/dev/null || true)"
target="${1:-$previous}"
if [[ -z "$target" ]]; then
  echo "error: no previous release is recorded; name a tag: rollback.sh --force <tag>" >&2
  exit 2
fi
if [[ "$target" != "$previous" && "$force" != true ]]; then
  echo "error: $target is not the previous release (${previous:-none}); only that one is" \
    "sure to run on the current schema. If no release since $target dropped anything" \
    "it reads, run: rollback.sh --force $target" >&2
  exit 2
fi
exec bash "$(dirname "$0")/deploy.sh" --rollback "$target"
