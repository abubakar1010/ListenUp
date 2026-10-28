# Stage 0 host: provision and record (spike #16)

For the owner. About 30 minutes if Oracle has capacity. Choice and limits: [ADR 0073](../adr/0073-stage-0-host-oracle-always-free-arm.md) (Proposed until step 9 is done). What runs on the host afterwards: [deploy.md](deploy.md). Nothing secret goes into the repository: private keys stay on your machine and in GitHub's secret store; only public keys and host facts are pasted anywhere.

**Read first.** Oracle's free Arm allowance is now **2 OCPUs and 12 GB** (checked 2026-10-27), not the 4 cores and 16 GB the design assumed. The release workflow also builds **amd64 images only**, so this VM cannot run a release until the follow-ups in ADR 0073 are done. The VM is still the right place to run benchmarks B1 to B4 now (build the media image on the VM, step 8).

## 1. Account (10 minutes)

1. Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) with a card (identity check; Always Free resources are not billed). Use one email you control for recovery.
2. **Choose the home region carefully.** It cannot be changed, and Always Free VMs and volumes can only be created there. Pick a region you can reach with low latency; for a US audience a region other than the busiest ones is more likely to have Arm capacity (capacity is not guaranteed anywhere). Do not pick South Korea North (Chuncheon): no free A1 there.
3. Turn on multi-factor sign-in for the account.
4. In **Billing → Cost analysis**, check the account shows no paid resources. Do not upgrade to pay as you go unless step 4's capacity problem needs it (ADR 0073, fallback 1).

## 2. SSH keys (3 minutes, on your machine)

Make one key for you and one for the release workflow. Keys never enter the repository.

```sh
ssh-keygen -t ed25519 -C "listenup-owner"      -f ~/.ssh/listenup_owner   # your login
ssh-keygen -t ed25519 -C "listenup-release"    -f ~/.ssh/listenup_release -N ""   # GitHub's key, no passphrase
```

Keep `listenup_release` (private) only for step 7. You will paste the two **`.pub`** files below.

## 3. Network: security list (3 minutes)

Console → Networking → Virtual cloud networks → your VCN → the public subnet's **Security list** → add **ingress rules** (source `0.0.0.0/0`, stateful):

| Protocol | Port | Why |
| --- | --- | --- |
| TCP | 22 | SSH. GitHub's runners connect from changing addresses, so it cannot be limited to your own address; key-only login and fail2ban protect it. To reduce scanning, set another port and `LISTENUP_DEPLOY_SSH_PORT` (deploy.md step 11). |
| TCP | 80 | HTTP, redirected to HTTPS; ACME challenge. |
| TCP | 443 | HTTPS. |
| UDP | 443 | HTTP/3. |

Nothing else. If you create the VM from the wizard's default VCN, it already has an ingress rule for 22. Egress stays at the default allow-all.

## 4. Create the VM (5 minutes)

Console → Compute → Instances → **Create instance**.

| Field | Value |
| --- | --- |
| Name | `listenup-stage0` |
| Placement | Your home region. Any availability domain; if you get "out of host capacity", try the other availability domains, then wait and retry later in the day. |
| Image | **Canonical Ubuntu 24.04** (aarch64 build; the wizard picks the right one for an Ampere shape) |
| Shape | Change shape → Ampere → **VM.Standard.A1.Flex**, **2 OCPUs, 12 GB** (the whole free allowance). Total A1 across the tenancy must stay at 2 OCPUs and 12 GB: check Compute → Instances for old instances first. |
| Networking | The public subnet, **assign a public IPv4 address** |
| SSH keys | Paste `~/.ssh/listenup_owner.pub` |
| Boot volume | **Specify a custom size: 100 GB** (Always Free storage is 200 GB in total for boot and block volumes) |
| Advanced → Cloud-init | Paste the script below (or leave empty and run `provision-host.sh` by hand in step 5) |

Cloud-init (user data). Replace `<RELEASE_PUBLIC_KEY>` with the single line from `~/.ssh/listenup_release.pub`. It is a public key, so it is safe to paste.

```yaml
#cloud-config
package_update: true
packages: [git]
runcmd:
  - [bash, -c, "git clone --depth 1 https://github.com/abubakar1010/ListenUp.git /root/listenup-src && LISTENUP_DEPLOY_PUBKEY='<RELEASE_PUBLIC_KEY>' bash /root/listenup-src/infra/deploy/provision-host.sh > /var/log/listenup-provision.log 2>&1"]
```

The clone works only while the repository is public. If it is private, leave cloud-init empty and copy `infra/deploy/provision-host.sh` over in step 5.

If creation fails with "out of host capacity" for every availability domain over a few days, stop and see ADR 0073 (fallback). A third-party retry script exists but is not reviewed or endorsed here.

## 5. First login and provisioning (5 minutes)

```sh
ssh -i ~/.ssh/listenup_owner ubuntu@<public ip>
tail -f /var/log/listenup-provision.log      # if you used cloud-init; ends with the Docker versions
```

Without cloud-init, copy the script and run it (the default user `ubuntu` has sudo):

```sh
scp -i ~/.ssh/listenup_owner infra/deploy/provision-host.sh ubuntu@<public ip>:
ssh -i ~/.ssh/listenup_owner ubuntu@<public ip> \
  "LISTENUP_DEPLOY_PUBKEY='$(cat ~/.ssh/listenup_release.pub)' sudo -E bash provision-host.sh"
```

What the script does (read it first: `infra/deploy/provision-host.sh`): installs Docker Engine and the Compose plugin from Docker's apt repository (deploy.md needs Engine 28+ and Compose 2.24+), creates the `deploy` user in the `docker` group with only the release **public** key, turns off password and root SSH, adds a 4 GB swap file, opens ports 80, 443/tcp and 443/udp in the host's iptables (Oracle's Ubuntu image rejects everything but SSH there, in addition to the security list), and enables fail2ban and unattended upgrades. It creates `/opt/listenup`. It does not create `.env` (deploy.md step 9).

**Check.** From your machine, `ssh -i ~/.ssh/listenup_release deploy@<public ip> docker version` prints Client and Server versions; Engine must be 28 or later. Ports: `nc -vz <public ip> 443` fails until Caddy runs, but is **not** "filtered"; test again after the first deploy.

## 6. Record the host facts (2 minutes)

From your machine:

```sh
scp -i ~/.ssh/listenup_owner infra/deploy/host-facts.sh ubuntu@<public ip>:
ssh -i ~/.ssh/listenup_owner ubuntu@<public ip> bash host-facts.sh
```

It prints the date, architecture, OS, kernel, **CPU model, cores, threads per core, memory, swap, disk**, cgroup version (the deploy rehearsal ran on cgroup v1; this host should be v2), Docker and Compose versions, and the Arm CPU feature flags. It reads nothing secret. Paste the output into the table below in a pull request (or a comment on #16), with these two extra checks:

```sh
docker run --rm --platform linux/arm64 python:3.12-slim python -c "import platform; print(platform.machine())"   # aarch64
for i in python:3.12-slim node:22-alpine caddy:2.10.2-alpine haproxy:3.2.4-alpine; do
  echo "$i: $(docker buildx imagetools inspect "$i" | grep -c 'linux/arm64')"; done   # each must be 1 or more
```

| Fact | Value |
| --- | --- |
| Date, UTC | _to fill_ |
| Cloud, region, availability domain, shape | _Oracle, ?, ?, VM.Standard.A1.Flex_ |
| Architecture, OS, kernel | _to fill_ |
| CPU model, cores, threads per core | _to fill_ |
| Memory, swap | _to fill_ (expect 12 GiB) |
| Disk (root total, free) | _to fill_ (expect about 100 GB) |
| cgroup, Docker, Compose | _to fill_ |
| `arm64` manifests for the four base images | _to fill_ |

## 7. Give the GitHub deploy workflow access (5 minutes)

Settings → Environments → **production** (create it; optionally add yourself as required reviewer). Add:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `DEPLOY_HOST` | the VM's public IP or DNS name |
| Secret | `DEPLOY_USER` | `deploy` |
| Secret | `DEPLOY_SSH_KEY` | the **private** key file `~/.ssh/listenup_release` (the whole file, as the secret value) |
| Secret | `DEPLOY_SSH_KNOWN_HOSTS` | the output of `ssh-keyscan -t ed25519 <public ip>`. First check its fingerprint (`ssh-keygen -lf` on that line) equals `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` run on the VM over your own login |
| Variable | `LISTENUP_PUBLIC_URL` | `https://<domain>` once DNS exists |

Do **not** set `LISTENUP_DEPLOY_ENABLED` to `true` yet: the images are amd64 only (ADR 0073 follow-up 1, [#231](https://github.com/abubakar1010/ListenUp/issues/231)) and the database, storage, SMTP and DNS steps of [deploy.md](deploy.md) come first. Test the SSH access by hand with the release key (step 5's check) and delete the private key from your machine once it is in GitHub, or keep it in a password manager. Rotation: deploy.md, "Secrets and their rotation".

## 8. Run the benchmarks on this VM (outside this runbook's 30 minutes)

On the VM, as `deploy`, with the repository checked out (`git clone` over HTTPS):

1. Build the media image natively for arm64: `docker build -f infra/docker/backend.Dockerfile --target worker-media -t listenup-worker-media:arm64-test .`. **Expect the `praat-parselmouth` step to compile from source** (no Arm wheel exists); if it fails because CMake or a C++ compiler is missing, that confirms ADR 0073 follow-up 2, and the build output goes in the record. Report how long it took.
2. Use a `compose.host.yml`-style override of `mem_limit: 7g` and `memswap_limit: 9g` for `worker-media` (the file's 18g is more than the VM has) and run one media process of 2 threads. Record the peak resident memory (`docker stats`).
3. Run B1 to B4 per `docs/spikes/` and compare per-core-second numbers with ADR 0034's. Run B5 on a 4-vCPU trial-credit VM instead (ADR 0073, decision 3).
4. Weekly: `docker stats --no-stream` and `uptime`. Oracle may reclaim a VM whose CPU (95th percentile), network and memory are **all** below 20% for 7 days (checked 2026-10-27); a loaded speech model keeps memory above 20% but CPU is idle between runs. If you see a reclaim notice, tell the team; do not add a fake load generator.

## 9. Finish the spike

1. Open a pull request that fills the table in step 6 and changes ADR 0073's status to **Accepted** (or a new ADR if the fallback was used). Link it to #16 (`Refs #16`).
2. Close #16 when the acceptance criteria hold: a VM with Docker is reachable by the team and documented here, and the ADR records the host, its limits on the date, and the fallback.
3. Check the Arm follow-ups [#231](https://github.com/abubakar1010/ListenUp/issues/231), [#232](https://github.com/abubakar1010/ListenUp/issues/232), [#233](https://github.com/abubakar1010/ListenUp/issues/233) and [#234](https://github.com/abubakar1010/ListenUp/issues/234) are done or consciously deferred before the live cutover (#112).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| "Out of host capacity" | Try another availability domain; retry later; see ADR 0073 fallback 1. |
| SSH works, ports 80/443 time out | The security list (step 3) or host iptables (`sudo iptables -S INPUT`) is missing the rule. |
| `permission denied` for `docker` | You are not in the `docker` group yet: log out and in, or use the `deploy` user. |
| `exec format error` on a pulled image | The image is amd64 only: ADR 0073 follow-up 1 ([#231](https://github.com/abubakar1010/ListenUp/issues/231)). |
| The instance was stopped by Oracle | Idle or over-limit reclaim; check that total A1 is 2 OCPUs and 12 GB and read ADR 0073. |
