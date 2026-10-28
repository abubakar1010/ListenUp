#!/usr/bin/env bash
# Print the host facts the stage 0 record needs (ADR 0070, docs/runbooks/stage-0-host.md).
# Read-only and secret-free: safe to paste into an issue or the runbook's record.
set -euo pipefail

echo "date_utc:        $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "architecture:    $(uname -m)"
os_name="$(grep -m1 ^PRETTY_NAME= /etc/os-release | cut -d= -f2- | tr -d \")"
echo "os:              $os_name"
echo "kernel:          $(uname -r)"
echo "cpu_model:       $(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2; exit}')"
echo "cpu_vendor:      $(lscpu | awk -F: '/Vendor ID/ {gsub(/^ +/, "", $2); print $2; exit}')"
echo "cores_online:    $(nproc)"
echo "threads_per_core: $(lscpu | awk -F: '/Thread\(s\) per core/ {gsub(/ /, "", $2); print $2}')"
echo "memory_total:    $(awk '/MemTotal/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
echo "swap_total:      $(awk '/SwapTotal/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
echo "root_disk:       $(df -h --output=size,avail / | tail -1 | awk '{print $1 " total, " $2 " free"}')"
if [[ -d /sys/fs/cgroup/cgroup.controllers || -f /sys/fs/cgroup/cgroup.controllers ]]; then
  echo "cgroup:          v2"
else
  echo "cgroup:          v1"
fi
if command -v docker >/dev/null; then
  engine="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" || engine="not reachable (docker group?)"
  compose="$(docker compose version --short 2>/dev/null)" || compose="missing"
  echo "docker:          $engine"
  echo "compose:         $compose"
fi
echo "cpu_flags_arm:   $(lscpu | awk -F: '/Flags/ {print $2}' | tr ' ' '\n' | grep -E '^(asimd|asimddp|fphp|sve|i8mm|bf16)$' | sort -u | tr '\n' ' ')"
