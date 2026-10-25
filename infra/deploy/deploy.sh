#!/usr/bin/env bash
# Deploy one release of ListenUp on the production host (#112, Architecture 11).
#
#   deploy.sh <tag>                  pull, check the buckets, migrate, restart
#   deploy.sh --rollback <tag>       pull and restart only (used by rollback.sh)
#
# <tag> is an immutable image tag built by the release workflow: sha-<12 hex> or
# r<number>. The deploy directory (LISTENUP_DEPLOY_DIR, default /opt/listenup) holds
# compose.prod.yml, its config files and the .env with the secrets; state/ records
# the current and previous release. Docker must already be logged in to the registry.
#
# Order: pull every image first, so a missing image fails before anything changes;
# refuse a public bucket; run migrations as a one-off container while the old release
# still serves (migrations are expand-only, Database Design 12.2); then replace the
# containers and wait for their health checks. A failure before the restart leaves
# the running release alone. If the new release never becomes healthy, the previous
# containers are started again (no migration runs backwards) and the deploy fails.
set -euo pipefail

dir="${LISTENUP_DEPLOY_DIR:-/opt/listenup}"
state="$dir/state"
mode=deploy

usage() {
  echo "usage: deploy.sh [--rollback] <tag>   (tag: sha-<12 hex> or r<number>)" >&2
  exit 2
}

if [[ "${1:-}" == "--rollback" ]]; then
  mode=rollback
  shift
fi
[[ $# -eq 1 ]] || usage
tag="$1"
if [[ ! "$tag" =~ ^(sha-[0-9a-f]{12}|r[0-9]+)$ ]]; then
  echo "error: '$tag' is not an immutable release tag" >&2
  usage
fi
for file in compose.prod.yml .env; do
  if [[ ! -f "$dir/$file" ]]; then
    echo "error: $dir/$file is missing (see docs/runbooks/deploy.md, first-time setup)" >&2
    exit 2
  fi
done

compose() {
  LISTENUP_IMAGE_TAG="$1" docker compose --project-name listenup --env-file "$dir/.env" \
    --file "$dir/compose.prod.yml" "${@:2}"
}

current="$(cat "$state/current-tag" 2>/dev/null || true)"

echo "==> $mode $tag (running: ${current:-none})"
compose "$tag" pull --quiet

if [[ "$mode" == deploy ]]; then
  if ! compose "$tag" run --rm --no-deps storage-check; then
    echo "error: storage check failed: a bucket is public or could not be checked; nothing changed" >&2
    exit 1
  fi
  if ! compose "$tag" run --rm --no-deps migrate; then
    echo "error: migrations failed; the running release ${current:-none} is untouched" >&2
    exit 1
  fi
fi

if ! compose "$tag" up --detach --wait --remove-orphans; then
  if [[ -n "$current" && "$current" != "$tag" ]]; then
    echo "error: $tag did not become healthy; starting $current again" >&2
    compose "$current" up --detach --wait --remove-orphans
    echo "error: restored $current; $tag is not deployed" >&2
  else
    echo "error: $tag did not become healthy" >&2
  fi
  exit 1
fi

mkdir -p "$state"
if [[ -n "$current" && "$current" != "$tag" ]]; then
  echo "$current" > "$state/previous-tag"
fi
echo "$tag" > "$state/current-tag"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $mode $tag previous=${current:-none}" >> "$state/releases.log"
echo "==> $tag is live"
