#!/usr/bin/env bash
# Roll production back to the previous release, or to a named one (#112).
#
#   rollback.sh          the release recorded in state/previous-tag
#   rollback.sh <tag>    any earlier release still in the registry
#
# Only the images change: migrations are expand-only (Database Design 12.2), so the
# older code runs on the newer schema and nothing is migrated backwards. Afterwards
# state/previous-tag names the release rolled away from, so a second rollback
# returns to it. See docs/runbooks/deploy.md.
set -euo pipefail

dir="${LISTENUP_DEPLOY_DIR:-/opt/listenup}"
target="${1:-$(cat "$dir/state/previous-tag" 2>/dev/null || true)}"
if [[ -z "$target" ]]; then
  echo "error: no previous release is recorded; name a tag: rollback.sh <tag>" >&2
  exit 2
fi
exec bash "$(dirname "$0")/deploy.sh" --rollback "$target"
