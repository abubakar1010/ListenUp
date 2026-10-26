# Stage-0 benchmark host: owner setup and verification

Status: **blocked; no host provisioned or reachable host verified**.
Checked 2026-10-27 (Asia/Dhaka; 2026-10-26 UTC).
Decision, provider sources and compatibility findings: [ADR 0067](../adr/0067-stage-zero-host-eligibility-and-provisioning-gate.md).

This checklist provisions the host and Docker only. Do not run the application,
`deploy.sh`, migrations, model provisioning, or the Release workflow. Do not set
`LISTENUP_DEPLOY_ENABLED=true`, install a production Actions SSH key, or configure
production secrets. [#112's runbook](deploy.md) owns those later steps.

## 1. Resolve ownership, cost and availability

- [ ] Owner identifies an existing authorized amd64 host or grants a scoped
  provisioning identity through the supported environment configuration. Never
  send private keys, API keys or account passwords in chat or commit them.
- [ ] Confirm four sustained cores, 24 GiB RAM, 80 GiB SSD, Ubuntu 24.04 LTS,
  outbound HTTPS, a stable team-reachable SSH endpoint, and zero incremental cost
  including disk, IP, traffic, backups and licensing. Record who pays and why
  the arrangement continues after any trial. Shared workstation contention
  must be eliminated or recorded; a laptop is not an always-on deployment host.
- [ ] For the conditional OCI alternative, owner opens Governance & Administration
  → Tenancy Management → Limits, Quotas and Usage in the **home region**. Record
  available A1 cores/memory, existing allocations and remaining boot/block storage.
  Quota is not a billing allowance: obtain account-specific recurring 4/24
  eligibility from billing/support to resolve the conflicting official pages.
  Confirm zero recurring cost without credits; do not upgrade to paid, request
  paid capacity or launch 4/24 based solely on a free-eligible label.
- [ ] Resolve the Arm native-build/release blockers in ADR 0067 before choosing
  OCI A1. If eligible, create `listenup-stage0-bench`, `VM.Standard.A1.Flex`,
  4 OCPUs, 24 GB RAM, official Ubuntu 24.04 arm64 image, 80 GB boot volume,
  standard free-eligible storage performance, in the home region. Count all
  existing volumes against 200 GB; do not add paid volumes, Marketplace images,
  NAT gateways or load balancers. Record actual region, availability domain,
  image ID, shape and creation timestamp. If out of capacity, try another home
  region AD or wait; do not silently switch shape/region or reduce requirements.
- [ ] Confirm the reviewed route/IP arrangement is free before creation. For a
  public host, use a public subnet and internet gateway with only TCP 22 inbound
  from the team's known source ranges. Do not open 80/443 yet. Do not expose the
  Docker API. Preserve working SSH/console access before changing firewall rules.
- [ ] If no qualifying allocation is available, stop and leave #16 open. Budget
  alerts do not enforce a zero-spend ceiling. An owner decision is required to
  change the target or fund a host; trial credit is not an always-free fallback.

## 2. Establish team SSH access

- [ ] Owner installs each authorized person's **public** key using their provider
  or existing VM access. Prefer separate named accounts; use the image's initial
  `ubuntu` account for bootstrap only. Grant sudo only to designated maintainers.
  Private keys remain with each person; this is independent of #112's deploy key.
- [ ] From the provider console or another trusted channel, record the host's
  Ed25519 fingerprint: `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
  Compare it with the client-observed key before accepting it. Do not use
  `StrictHostKeyChecking=no`; `ssh-keyscan` alone is not verification.
- [ ] Team member verifies a separate connection with their own key. Record
  username, host or access-record location, port, fingerprint, allowed source
  ranges and access owner in the inventory below. For a private host, document
  the authorized VPN/bastion path and verify that path from the team's client.

Client template (replace placeholders locally):

```sshconfig
Host listenup-stage0
    HostName <verified-host>
    User <your-account>
    Port 22
    IdentityFile <your-local-private-key-path>
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

## 3. Install Docker and Compose on the fresh host

Run on the chosen Ubuntu 24.04 host, not the managed development container.
These are owner execution instructions; they have **not** been executed on a
benchmark host. Follow the [official Docker apt instructions](https://docs.docker.com/engine/install/ubuntu/).
If an existing Docker/containerd installation is present, inventory it and its
workloads first; do not remove packages or overwrite daemon configuration blindly.

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
apt-cache policy docker-ce docker-ce-cli docker-compose-plugin
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker buildx version
```

- [ ] Record exact installed package versions, not examples copied from docs.
  Require server Engine >=28 and Compose >=2.24; use supported stable packages.
- [ ] Use `sudo docker` for the host check. Docker group membership grants
  root-equivalent control; do not add every team member automatically.
- [ ] Confirm normal system CA verification and outbound package/image access.
  If running these checks through the managed cloud environment, follow its
  Docker/proxy/CA instructions; do not bypass a policy or disable TLS checking.

## 4. Verify host resources and Docker enforcement

Record safe output from these commands; do not collect environment dumps,
credential files, full Docker configuration or application inspection output.

```sh
date -u +'%Y-%m-%dT%H:%M:%SZ'
cat /etc/os-release
uname -srmo
lscpu
nproc
free -b
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
df -B1 / /var/lib/docker
swapon --show --bytes
stat -fc %T /sys/fs/cgroup
dpkg-query -W docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl is-active docker
sudo docker info --format 'Architecture={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}} Cgroup={{.CgroupVersion}} Driver={{.CgroupDriver}} Security={{json .SecurityOptions}}'
sudo docker run --rm hello-world
```

Use a disposable generic Ubuntu container to check cgroup settings without
starting any application. The 256 MiB/1 CPU values below are smoke-test limits,
not the production budget. Record the pulled image digest.

```sh
sudo docker run --rm --cpus=1 --memory=256m --memory-swap=256m --pids-limit=64 ubuntu:24.04 sh -c '
  if test -f /sys/fs/cgroup/cgroup.controllers; then
    cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max /sys/fs/cgroup/pids.max
  else
    cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us /sys/fs/cgroup/cpu/cpu.cfs_period_us
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes /sys/fs/cgroup/memory/memory.memsw.limit_in_bytes /sys/fs/cgroup/pids/pids.max
  fi
  cat /proc/self/status | sed -n "/^Seccomp:/p"
'
sudo docker image inspect ubuntu:24.04 --format '{{json .RepoDigests}}'
sudo docker network create --internal --driver bridge --opt com.docker.network.bridge.gateway_mode_ipv4=isolated listenup-stage0-check
sudo docker network inspect listenup-stage0-check --format 'Internal={{.Internal}} Options={{json .Options}}'
sudo docker network rm listenup-stage0-check
```

- [ ] Require cgroup v2 values: `cpu.max` quota/period ratio 1, memory 268435456,
  swap 0, pids 64; or equivalent cgroup v1 memory/memsw equality and CPU ratio.
  Require seccomp mode 2. Unexpected paths/missing controllers are a failed check
  to investigate, not a pass. No Docker resource-limit warnings may be ignored.
- [ ] Confirm internal/isolated bridge options and remove only the named test
  network. These smoke checks prove configuration support, not complete media
  boundary enforcement or real-model performance; #112/#155 still own that work.
- [ ] Record host CPU quota/cpuset if this VM itself is nested or constrained.
  Require four usable sustained cores and at least 24 GiB nominal RAM (document
  provider decimal GB versus guest GiB), not merely four visible processors.
  For OCI's conditional 24 GB allocation, verify measured available headroom
  explicitly rather than treating decimal GB as 24 GiB.
- [ ] Recommend swap absent for benchmarks. If present, record size/device and
  `vmstat` swap-in/out during later runs. Do not disable active swap on a used
  machine or count it as RAM. Current media limits prohibit container swap.
- [ ] Preserve at least 20 GiB disk headroom before later image/model checks.
  No stress test or application workload is run by this checklist.

## 5. Inventory and closeout gate

Replace pending entries only with observed evidence. Public repository records
may link to an owner-controlled access record if endpoint details are private;
the team must still be able to use it without asking for undocumented secrets.

| Field | Observed value |
| --- | --- |
| Provisioning state | Not provisioned; #16 open |
| Provider/host owner and recurring zero-cost evidence | Pending |
| Region/AD, shape/image, resource identifier | Pending |
| CPU model/architecture, physical/virtual cores, threads, sustained quota/cpuset | Pending |
| Total/available RAM in bytes, provider GB versus GiB | Pending |
| Disk type/capacity/free bytes, root/Docker filesystem | Pending |
| Host swap size, media swap allowance | Pending / configured media allowance is zero |
| OS/kernel/cgroup version and enforcement output | Pending |
| Engine/server, CLI, Compose, Buildx, containerd versions | Pending |
| SSH host/port/account or team access-record link | Pending |
| Verified SSH Ed25519 fingerprint and verification channel | Pending |
| Team reachability verifier and UTC timestamp | Pending |
| Docker hello-world, cgroup/seccomp/bridge smoke output and image digest | Pending |
| Rebuild/reclamation owner and recovery access | Pending |
| Application deployment / automatic production deployment | Not performed / not enabled by this task |

Keep #16 open until a real host is reachable by the team, Docker/Compose and
hardware/limits are verified, the inventory is filled without secrets, and the
ADR is accepted and merged. A documentation PR alone does not satisfy #16.
Real model/build/latency validation remains explicitly unverified; #112 must
resolve any image compatibility gap before deploying, and #155 gates launch.
