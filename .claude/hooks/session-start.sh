#!/usr/bin/env bash
# Prepares a Claude Code cloud session so work can start at once: PostgreSQL running with
# the local role and database, and the backend and web dependencies installed.
# Runs only in cloud sessions; on a developer's own machine it does nothing.
# Every step is idempotent and quick when there is nothing to do.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
log() { echo "[session-start] $*"; }

# PostgreSQL 16: the cluster does not start on its own after a container restart.
if command -v pg_ctlcluster >/dev/null 2>&1; then
  if ! pg_isready -h localhost -q 2>/dev/null; then
    pg_ctlcluster 16 main start >/dev/null 2>&1 || log "could not start PostgreSQL"
    for _ in 1 2 3 4 5 6 7 8 9 10; do pg_isready -h localhost -q 2>/dev/null && break; sleep 1; done
  fi
  if pg_isready -h localhost -q 2>/dev/null; then
    # The default LISTENUP_DATABASE_URL; the tests create throwaway databases as this role.
    su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname = 'listenup'\"" | grep -q 1 ||
      su postgres -c "psql -qc \"CREATE ROLE listenup LOGIN SUPERUSER PASSWORD 'listenup'\""
    su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname = 'listenup'\"" | grep -q 1 ||
      su postgres -c "psql -qc 'CREATE DATABASE listenup OWNER listenup'"
    log "PostgreSQL ready"
  fi
else
  log "PostgreSQL is not installed; database tests will skip"
fi

if command -v uv >/dev/null 2>&1; then
  (cd "$root/apps/api" && uv sync -q --frozen) && log "backend dependencies ready" ||
    log "uv sync failed"
fi

if command -v pnpm >/dev/null 2>&1; then
  (cd "$root/apps/web" && pnpm install --frozen-lockfile --silent >/dev/null 2>&1) &&
    log "web dependencies ready" || log "pnpm install failed"
fi

exit 0
