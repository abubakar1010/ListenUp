#!/usr/bin/env bash
# Records, from inside the benchmark container, the limits E4 requires: 2 CPUs (cpu.max
# quota/period), memory and no swap (memory.swap.max 0), and the thread setting. nproc
# still shows the host's cores, because --cpus is a quota, not a CPU set.
# Usage: container-facts.sh OUT_FILE   (CGROUP_ROOT overrides /sys/fs/cgroup for tests)
set -euo pipefail

out="${1:?usage: container-facts.sh OUT_FILE}"
cgroup="${CGROUP_ROOT:-/sys/fs/cgroup}"
mkdir -p "$(dirname "$out")"
{
  echo "# Container limits (CI-runner evidence (E4))"
  for file in cpu.max memory.max memory.swap.max; do
    echo
    echo "## $file"
    cat "$cgroup/$file" 2>/dev/null || echo "unavailable"
  done
  echo
  echo "## nproc"
  nproc
  echo
  echo "## threads"
  echo "OMP_NUM_THREADS=${OMP_NUM_THREADS:-unset}"
} >"$out"
