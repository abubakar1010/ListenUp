# Stage 0 benchmark host: provision and verify (#16)

Status, 2026-10-29: **blocked on authorized OCI/SSH access; no benchmark host verified**.
Owner-approved choice: Oracle Always Free Arm `VM.Standard.A1.Flex`, **2 OCPUs and
12 GB nominal RAM**, Ubuntu 24.04 aarch64, 100 GB boot volume. See
[ADR 0073](../adr/0073-stage-0-host-oracle-always-free-arm.md), still Proposed until
the host and team access are verified.

This explicitly differs from #16's original **four-core** target and the design's
four-core/16 GB assumption. It is an initial benchmark host, with no four-core,
learner-capacity or performance claim. All performance targets remain unchanged.
The managed development environment and Arm CI runners are not this host.

PRs [#238](https://github.com/abubakar1010/ListenUp/pull/238) and
[#239](https://github.com/abubakar1010/ListenUp/pull/239) are merged: all six images
have amd64/arm64 build support, and Parselmouth compiles in a throwaway stage.
Native Arm CI build/import checks are evidence of build support. They do not
verify a real published Release, this host's runtime, model quality or performance.
Those layers remain unverified by #16. Do not start a Release to provision the host.

## 1. Owner actions to unblock access

1. **Confirm account eligibility in Oracle Console.** Sign in or complete account
   setup yourself, including identity/card verification and MFA. Choose the home
   region carefully; it cannot be changed. Confirm the recurring Always Free
   allowance for **2 OCPUs/12 GB without trial credits**, existing A1 allocations,
   and remaining free boot/block storage (historical allowance: 200 GB combined).
   Check that the proposed disk, IP, networking, traffic and any backups incur no
   charges. Quota or a “free eligible” badge alone is not billing confirmation.
   Do not upgrade the account, consume credits or create paid resources.
2. **Choose an access route.** Prefer an existing authorized host if one exists.
   Otherwise either configure scoped OCI provisioning credentials and a supported
   SSH identity in the cloud environment's secure configuration, or create the
   VM using step 2 and run steps 3–4 from your own machine. Never send passwords,
   API credentials or private keys in chat or commit them. For remote work through
   the cloud environment, also configure a TCP destination grant for the exact
   host/SSH endpoint; unrestricted HTTP does not grant raw SSH access. Use the
   supported environment configuration workflow, not edits to its policy file.
3. **Return only non-secret confirmation:** account setup complete; home region;
   recurring 2/12 eligibility without credits; existing/free allocation remaining;
   existing instance or creation state/capacity error; and the access method.
   For a host, supply host/account/port and a trusted Ed25519 fingerprint, or a
   team-accessible controlled record containing them. Identify the access owner
   and each authorized team member who will verify their own connection.

Observed blocker in this session: no cloud identities, secret bindings or runtime
variables were configured; OCI CLI/profile and SSH config/known-hosts/agent were
absent; no host endpoint was supplied. The TCP policy grants no destinations.
The owner selected the Console/local-verification route; no results have yet been
returned. Account eligibility and capacity have **not** been tested by this session. No provider create or
SSH call was attempted. Documentation preparation continues independently.

## 2. Create or identify the approved VM

First inventory any existing authorized instance and its workloads. Do not replace
or resize a host without checking ownership. For a fresh VM, use Oracle Console →
Compute → Instances → Create instance:

| Field | Approved value/check |
| --- | --- |
| Name | `listenup-stage0` |
| Region/placement | Tenancy home region; record availability domain |
| Shape | `VM.Standard.A1.Flex`, **2 OCPUs, 12 GB**; check aggregate tenancy use fits the recurring allowance |
| Image | Official Canonical Ubuntu 24.04, aarch64; record image identifier |
| Boot volume | 100 GB, free-eligible performance; total existing boot/block use must remain within verified free storage |
| Networking | Team-reachable route; confirm any public IP/networking costs before creation |
| Ingress | TCP 22 only from authorized team source ranges, or a verified VPN/bastion route; do not expose Docker API or open application ports |
| SSH keys | Authorized people's public keys only; private keys stay with their owners |
| Cloud-init | Leave empty; use the Docker-only steps below |

If no A1 capacity is available, try another availability domain in the home
region or wait. Record the exact non-secret error and time. If account eligibility
or capacity remains unavailable, stop and ask the owner for a new decision;
no paid/trial-credit fallback is authorized.

Do not run `infra/deploy/provision-host.sh` for this limited task: that existing
script also creates a release-workflow user, adds swap and opens web ports.
Those broader deployment changes are unnecessary for #16. It is not modified here.
Production setup belongs to [#112's deployment runbook](deploy.md).

## 3. Verify team SSH and install Docker

1. Using the provider console or another trusted channel, obtain the server's
   fingerprint with `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
   Compare it with the client-observed host key before accepting the key.
   `ssh-keyscan` alone is not authentication. Use strict host-key checking for
   subsequent connections; never use `StrictHostKeyChecking=no`.
2. Install each authorized team member's public key in their intended account.
   Prefer separate named accounts; grant sudo only to designated maintainers.
   Keep the existing working SSH/console recovery route during setup. Record a
   separate successful connection by each intended team operator using their own
   key, with verifier and timestamp. A bootstrap login alone is not team access.
3. Copy the install commands below to the **actual approved VM**. Inspect any
   existing Docker/containerd installation and workloads first; do not blindly
   remove packages or overwrite daemon configuration. For an already installed
   compatible version, verify it rather than reinstalling it.

Follow the [official Docker Ubuntu installation guide](https://docs.docker.com/engine/install/ubuntu/).
On a fresh Ubuntu 24.04 VM:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF_DOCKER
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF_DOCKER
sudo apt-get update
apt-cache policy docker-ce docker-ce-cli docker-compose-plugin
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker buildx version
```

Require **server Engine 28+ and Compose 2.24+**, and record exact observed versions.
Use `sudo docker`; Docker group membership grants root-equivalent control and is
not required for all team members. Keep normal CA/TLS verification enabled.
Do not install application secrets, production Actions SSH keys, model weights or
application services. Do not set `LISTENUP_DEPLOY_ENABLED=true`.

## 4. Record hardware and smoke-check Docker

Run only on the actual host. Save safe output and timestamps for the inventory;
do not dump the environment, credential files, Docker config or application state.
`infra/deploy/host-facts.sh` is an optional summary; the checks below also record
usable CPU, byte counts and Docker enforcement.

```sh
date -u +'%Y-%m-%dT%H:%M:%SZ'
cat /etc/os-release
uname -srmo
lscpu
nproc
free -b
swapon --show --bytes
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
df -B1 / /var/lib/docker
stat -fc %T /sys/fs/cgroup
dpkg-query -W docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl is-active docker
sudo docker info --format 'Architecture={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}} Cgroup={{.CgroupVersion}} Driver={{.CgroupDriver}}'
sudo docker run --rm hello-world
sudo docker image inspect hello-world --format 'Architecture={{.Architecture}} Digests={{json .RepoDigests}}'
```

Require aarch64/arm64, two usable cores, and RAM consistent with the approved
12 GB allocation, recording provider GB versus guest GiB. If nested or otherwise
constrained, record host CPU quota/cpuset; visible processors alone are insufficient.
Record root/Docker disk capacity and free bytes, disk type and any swap. Swap is
not RAM; do not disable existing swap blindly. No stress test is required.

Use a disposable generic container for resource checks. These limits are smoke
values, not application budgets:

```sh
sudo docker run --rm --platform linux/arm64 --cpus=1 --memory=256m --memory-swap=256m --pids-limit=64 ubuntu:24.04 sh -ec '
  uname -m
  test -f /sys/fs/cgroup/cgroup.controllers
  cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max /sys/fs/cgroup/pids.max
  sed -n "/^Seccomp:/p" /proc/self/status
'
sudo docker image inspect ubuntu:24.04 --format 'Architecture={{.Architecture}} Digests={{json .RepoDigests}}'
sudo docker network create --internal --driver bridge --opt com.docker.network.bridge.gateway_mode_ipv4=isolated listenup-stage0-check
sudo docker network inspect listenup-stage0-check --format 'Internal={{.Internal}} Options={{json .Options}}'
sudo docker network rm listenup-stage0-check
```

For the Ubuntu 24.04/cgroup-v2 setup, require `cpu.max` quota/period ratio **1**,
`memory.max` **268435456**, `memory.swap.max` **0**, `pids.max` **64**, and Seccomp
**2**. Require `Internal=true` and gateway mode `isolated`; remove only the test
network created above. If that name already exists, inspect ownership and choose
an unused test name. Missing controllers, unsupported limits, Docker warnings or
unexpected values are failures to investigate, not a pass. For an existing host
using cgroup v1, document it and verify equivalent CPU/memory/memsw/pids controls
before accepting it; these v2 commands do not prove v1 support.

These checks prove basic Docker execution and configured limit support, not
complete media sandbox enforcement, real-model performance or production readiness.
Current production media limits are 18 GiB memory with **no container swap**;
that ceiling exceeds this host's RAM. #16 changes no limits or worker concurrency.
A later workload session must establish and record appropriate benchmark budgets.

## 5. Host inventory

Fill only with observed evidence. Never copy expected values into observed fields.
Endpoint details may live in a controlled team-accessible record; credentials must
remain outside the repository. Preserve command output in a sanitized evidence
record linked here when verification is possible.

| Fact | Observed value |
| --- | --- |
| Verification date/time, UTC | Pending |
| Provisioning state | No authorized host supplied or verified in this session; #16 open |
| Host/access/rebuild owner | Pending owner confirmation |
| Account recurring free eligibility and existing allocations | Pending; no credits, upgrade or paid resources authorized |
| Provider, region, AD, shape, instance/image identifier | Pending; approved shape is A1.Flex 2 OCPUs / 12 GB, not an observed allocation |
| CPU model, architecture, topology, usable cores, quota/cpuset | Pending |
| RAM total/available bytes; provider GB versus guest GiB | Pending |
| Swap size/device | Pending |
| Root/Docker disk type, total/free bytes | Pending |
| OS, kernel, cgroup version/driver | Pending |
| Docker server/CLI, Compose, Buildx, containerd versions | Pending |
| SSH endpoint/account/port or controlled team-access record | Pending |
| Host-key fingerprint and trusted verification channel | Pending |
| Team operators' separate successful SSH verification/timestamps | Pending |
| hello-world result, architecture and digest | Not run on benchmark host |
| CPU/memory/swap/pids/seccomp output and test image digest | Not run on benchmark host |
| Internal/isolated bridge result and cleanup | Not run on benchmark host |
| Real published Arm Release / application performance | Unverified; outside #16 |
| Production / automatic deployment | Not performed / not enabled by this task |

## 6. Completion and separate-session handoff

Keep ADR 0073 Proposed until the host exists and team access plus checks succeed.
One PR must contain the observed inventory, evidence and ADR update. Use **Refs
#16**, not an automatic closing keyword. The owner merges after required CI and
fresh-session review; keep #16 open until its revised two-core acceptance criteria
are actually satisfied. A documentation-only merge does not satisfy them.

**#17 readiness: blocked.** No real host, team SSH or Docker/resource check has
been verified. After those gates succeed, record readiness for a separate #17
feasibility session on the two-core host. Do not run #17's video measurements,
implement YouTube intake, run B1–B5, deploy production or enable automatic deployment
in this session. Image build support and host provisioning alone establish no
performance target result. #233 owns speech remeasurement; #112/#155 retain
application deployment and launch-validation gates.
