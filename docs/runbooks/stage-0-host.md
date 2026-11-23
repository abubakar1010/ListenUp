# Stage 0 host: provision and verify (#16)

For the owner. This covers the Hostinger KVM 4 VPS chosen in [ADR 0101](../adr/0101-stage-0-host-hostinger-kvm-4-vps.md) (owner exception E6): the OS, SSH and firewall settings in hPanel, Docker, the read-only checks, and the record of what was observed. The application itself is set up by [deploy.md](deploy.md) under #112. The speech benchmarks B1 to B4 do not run here: they run on GitHub's Arm runners (E4).

**Nothing secret goes into this repository, and the repository is public.**

- **Leave out of the repository:** the server's IP address, the hPanel account, root credentials and private keys. Do not paste them into issues or pull requests either.
- **Where the team finds the endpoint:**
  - in hPanel, under VPS → Overview (owner access);
  - once #112 sets it, in the `production` environment secret `DEPLOY_HOST` on GitHub;
  - team members who need SSH get it from the owner privately.

## 1. hPanel: operating system, SSH key, firewall

Menu names are as hPanel showed them in November 2026 and may move.

1. **OS.** hPanel → VPS → **OS & Panel → Operating system**: plain **Ubuntu 26.04 LTS**, without a control panel. Reinstalling the OS wipes the disk and gives the host a new SSH host key (then update `known_hosts` and `DEPLOY_SSH_KNOWN_HOSTS`).
2. **SSH key.** hPanel → VPS → **Settings → SSH keys**: add your own public key (`ssh-keygen -t ed25519 -C "listenup-owner" -f ~/.ssh/listenup_owner`, then paste `listenup_owner.pub`). Only the `.pub` file is pasted anywhere. The release workflow's own key is created in #112 (deploy.md step 3).
3. **Host key, before the first login.** Open hPanel's **browser terminal** and run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Keep that fingerprint. On the first `ssh` from your machine, accept the key only if the ED25519 fingerprint it shows is the same.
4. **SSH login.** Key login only: `PasswordAuthentication no` and `PermitRootLogin prohibit-password` (check with `sshd -T | grep -iE '^(passwordauthentication|permitrootlogin)'`). If password login is still on, turn it off only after a key login has worked: set `PasswordAuthentication no` in `/etc/ssh/sshd_config`, run `systemctl restart ssh`, then confirm a **new** key login works before closing the old session.
5. **Firewall (in #112, not in this runbook's checks).** hPanel → VPS → **Security → Firewall**: allow inbound TCP 22, TCP 80, TCP 443 and UDP 443, and nothing else (deploy.md step 2). GitHub's runners connect from changing addresses, so port 22 cannot be limited to your own address. Do not open web ports before #112's first deploy.

## 2. Docker

The KVM 4 came with Docker installed from Docker's own apt repository (packages `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, `docker-compose-plugin`; `/etc/apt/sources.list.d/docker.list`). `deploy.md` needs **Engine 28 or later and Compose 2.24 or later** (ADR 0049's isolated bridge). Check with:

```sh
docker version --format '{{.Server.Version}}'; docker compose version
```

If Docker is missing or too old, install it from Docker's apt repository (as root; the codename comes from the OS, so this works on 26.04):

```sh
apt-get update && apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Do not install Ubuntu's `docker.io` package next to these.

## 3. Checks (read-only, about 2 minutes)

Run as root over SSH. The block writes its output to `~/stage0-report.txt`. It pulls `hello-world` and `ubuntu:24.04`, and creates and removes one Docker network; it changes nothing else. Keep the report out of the repository: it holds the host's details but not secrets. Put its results into the record in section 4.

```sh
{
date -u; cat /etc/os-release; uname -srmo; lscpu; nproc; free -b; swapon --show --bytes
lsblk; df -B1 / /var/lib/docker; stat -fc %T /sys/fs/cgroup
docker version; docker compose version; docker buildx version
docker info --format 'Architecture={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}} CgroupVersion={{.CgroupVersion}} CgroupDriver={{.CgroupDriver}}'
docker run --rm hello-world
docker run --rm --cpus=1 --memory=256m --memory-swap=256m --pids-limit=64 ubuntu:24.04 sh -c \
  'cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max /sys/fs/cgroup/pids.max; grep ^Seccomp: /proc/self/status'
docker network create --driver bridge --internal -o com.docker.network.bridge.gateway_mode_ipv4=isolated listenup-stage0-check
docker network inspect listenup-stage0-check --format 'Internal={{.Internal}} Options={{json .Options}}'
docker network rm listenup-stage0-check
vmstat 5 12
} > ~/stage0-report.txt 2>&1
```

| Check | Pass when |
| --- | --- |
| Architecture | `x86_64` |
| CPUs | `nproc` and Docker's `CPUs` are 4 |
| Memory | about 16 GB (`free -b` total) |
| cgroup | `cgroup2fs` |
| Docker | Engine 28 or later, Compose 2.24 or later |
| Container limits | `100000 100000`, `268435456`, `0`, `64`, and `Seccomp: 2` |
| Internal network | `Internal=true` and `gateway_mode_ipv4` `isolated` |
| CPU steal | the `st` column of `vmstat` near 0 (see section 5 for load) |

## 4. Host record, 2026-11-23

Filled only from the output of section 3, run over SSH from the owner's machine on 2026-11-23 between 08:40 and 08:41 UTC. A value that was not observed is marked so.

| Fact | Observed |
| --- | --- |
| Provider, plan, data center | Hostinger, KVM 4, France (owner-stated; the data center is not visible from inside the VM) |
| Price | USD 114 for 12 months, paid yearly: USD 9.50 a month (owner-stated) |
| Architecture, OS, kernel | `x86_64`; Ubuntu 26.04.1 LTS (`resolute`); Linux 7.0.0-38-generic |
| CPU | AMD EPYC 9354P 32-Core Processor, KVM guest (full virtualisation); 4 vCPUs, 1 thread per core, 1 socket |
| Memory, swap | 16,763,596,800 bytes (15.6 GiB) total, 14.8 GiB available at check time; **no swap** |
| Disk | 200 GB disk; root `/dev/sda1` 207,071,854,592 bytes, 3% used. `/var/lib/docker` is on the root filesystem |
| cgroup | `cgroup2fs`; Docker CgroupVersion 2, CgroupDriver `systemd` |
| Docker | Engine 29.10.0 (API 1.57), containerd v2.4.2, runc 1.5.3; Compose v5.8.0; buildx v0.39.1; packages `5:29.10.0-1~ubuntu.26.04~resolute` from Docker's apt repository |
| Docker security options | apparmor, seccomp (builtin), cgroupns, no-new-privileges |
| SSH | `passwordauthentication no`, `permitrootlogin prohibit-password`, `pubkeyauthentication yes`; key login worked on every connection. Already set when checked, so nothing was changed |
| Host key | The ED25519 key trusted was the one already in the owner's `known_hosts`: `SHA256:COxdhMdZdQOPUjxaG4bV9y6B3Vkz0XOmO2ezDcMpRrg`. **Not yet compared** with the fingerprint shown in Hostinger's browser terminal (step 1.3); the owner waived that check for this session |
| Other software noticed | Hostinger's Monarx apt source (`monarx.list`). Whether its agent runs was not checked |
| Firewall, ports, users | Not checked and not changed: they belong to #112 |

| Check | Result |
| --- | --- |
| `x86_64` | **Pass** |
| 4 CPUs | **Pass** (`nproc` 4, Docker `CPUs=4`) |
| About 16 GB memory | **Pass** (15.6 GiB) |
| `cgroup2fs` | **Pass** |
| Engine 28+, Compose 2.24+ | **Pass** (29.10.0, v5.8.0) |
| `docker run --rm hello-world` | **Pass** |
| Limits print `100000 100000`, `268435456`, `0`, `64`, `Seccomp: 2` | **Pass**, all five as expected |
| Internal network `Internal=true`, isolated gateway | **Pass** (`{"com.docker.network.bridge.gateway_mode_ipv4":"isolated"}`); the network was removed afterwards |
| CPU steal near 0 | **Pass while idle**: `st` 0 in all 12 samples over 60 s. Not yet measured under load (section 5) |

Open items from this record:

- **Compare the host-key fingerprint** in the browser terminal (step 1.3). Do it before #112 stores `DEPLOY_SSH_KNOWN_HOSTS`.
- **Measure steal under load** (section 5).
- **Review the Monarx agent** before learner data reaches the host (ADR 0101).

## 5. Watching CPU steal

The vCPUs are shared with other tenants (ADR 0101). Run `vmstat 5 60` and note the `st` column:

- during the first real media jobs after #112's cutover;
- next to every #155 performance run (a result without its steal reading does not count);
- once a week.

| Average `st` under load | Do |
| --- | --- |
| up to 5% | Nothing. |
| above 5% over 5 minutes | Note it in #155 and measure again. |
| above 10% for an hour, or on most weekly checks | Raise it with Hostinger support, and ask the owner whether to move to a dedicated-CPU plan or another host (ADR 0101). |

## 6. Fitting the stack to 4 vCPUs and 16 GB

`infra/compose/compose.prod.yml` gives `worker-media` `cpus: 2`, `mem_limit: 18g` and `memswap_limit: 18g`. ADR 0049 sized the 18 GiB for two job slots of up to 8 GiB each (`LISTENUP_MEDIA_JOB_MEMORY_MB`, default 8192) plus the worker process. **18 GiB is more than this host's 15.6 GiB, and the host has no swap.** If the media worker really grew to 18 GiB, the kernel's out-of-memory killer would pick from every process on the host, possibly the API or Docker itself, instead of the cgroup stopping the media worker alone.

In #112, create **`/opt/listenup/compose.host.yml`** on the host. `deploy.sh` loads it after `compose.prod.yml` when it exists, and it is never in the repository:

```yaml
# Hostinger KVM 4: 4 vCPU, 15.6 GiB, no swap (ADR 0101, stage-0-host.md section 6).
services:
  worker-media:
    mem_limit: 12g
    memswap_limit: 12g
```

Check the merge with `LISTENUP_IMAGE_TAG=r1 docker compose -p listenup --env-file .env -f compose.prod.yml -f compose.host.yml config | grep -A3 'worker-media:' -m1` and the memory lines under it.

Why these values:

| | Value | Reason |
| --- | --- | --- |
| `worker-media` CPU | `cpus: 2`, unchanged | Half the 4 vCPUs. The API, default worker, Caddy, backups and the OS keep the other 2. Matches System Design 5.2 (fixed threads, no oversubscription). |
| `worker-media` memory | **12 GiB** (`mem_limit` and `memswap_limit` equal, so it never swaps) | ADR 0034 measured about 2.8 GB per media process at its peak (`small.en` plus the aligner), about 5.6 GB for two, so 12 GiB leaves room for ClamAV scans and conversions. It leaves about 3.6 GiB for the OS and Docker (0.8 GiB used on the idle host) and the small containers: Caddy, the API, the default worker, the signature updater, the relay and the backup job. |
| Job limit `LISTENUP_MEDIA_JOB_MEMORY_MB` | 8192, unchanged | It sets each job's address-space limit (`RLIMIT_AS`) as well as its RSS limit, and the real speech adapters were validated at 8 GiB. Lowering it could break them. Two jobs both near 8 GiB would now hit the container's 12 GiB first, and the cgroup stops the media worker alone, not the rest of the host. |
| Swap | none added here | Out of scope (#112). If `provision-host.sh` later adds its 4 GB swap file, the media worker still never swaps (`memswap_limit` = `mem_limit`), and the other containers gain a cushion. |

These are starting values. #112 records the real peak with `docker stats --no-stream` while media jobs run, and adjusts the override. Change `compose.prod.yml` itself only by a pull request that also updates ADR 0049 and `tests/unit/test_compose_prod.py`.

## 7. Hand-off to deploy.md (#112)

The host is ready for [deploy.md](deploy.md)'s first-time setup:

- **Step 1** (VM and Docker) is done and recorded above.
- **Steps 2 onwards are #112's work:**
  - the firewall (section 1.5);
  - the `deploy` user and the release key; `infra/deploy/provision-host.sh` covers this, so read it first;
  - DNS, the managed database, storage and SMTP;
  - the registry login and `.env`;
  - `compose.host.yml` (section 6);
  - GitHub's `production` environment, and the first deploy.

Do not run them as part of #16.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Host key verification failed` | The host key changed: an OS reinstall in hPanel, or someone in between. Compare with the browser terminal (step 1.3) before you replace the `known_hosts` line. |
| SSH works, ports 80/443 time out | hPanel's firewall (step 1.5) or the host's own iptables is missing the rule. |
| `permission denied` for `docker` | You are not root or in the `docker` group; use the `deploy` user after #112. |
| A container is killed with exit code 137 | Out of memory: check `docker stats` and section 6. |
| Jobs slower than the benchmarks | Check the steal in section 5 before tuning anything. |
