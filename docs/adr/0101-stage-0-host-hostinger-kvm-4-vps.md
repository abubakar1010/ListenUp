# ADR 0101: Stage 0 and production host: a Hostinger KVM 4 VPS in France

- Status: Accepted (owner exception E6, 2026-11-23; the host was verified the same day, see the runbook)
- Date: 2026-11-23
- Supersedes: [ADR 0073](0073-stage-0-host-oracle-always-free-arm.md) (Oracle Cloud Always Free Arm VM)
- Story: [#16](https://github.com/abubakar1010/ListenUp/issues/16); owner exception [E6 in #119](https://github.com/abubakar1010/ListenUp/issues/119#issuecomment-7095374552)
- Requirements: NFR-AI-3 (deviation, below); [Software Architecture 11](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 2 and 5.2](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADRs 0034, 0049, 0066 and 0073
- Runbook: [`docs/runbooks/stage-0-host.md`](../runbooks/stage-0-host.md) (provisioning, checks and the observed inventory)

## Context

ADR 0073 proposed Oracle Cloud's Always Free Ampere A1 VM (2 OCPUs, 12 GB) as the stage 0 host. That plan failed in two steps:

1. **Oracle refused the owner's card** at sign-up, so no Oracle account or VM was ever created. ADR 0073 never became Accepted.
2. **E5 (2026-11-01) made the owner's Mac the interim host. E6 (2026-11-23) withdrew it.** E6 decides that stage 0 runs on a rented VPS. That VPS is the single Docker Compose VM described in ADR 0066 and [`deploy.md`](../runbooks/deploy.md), so E5's pull-based deploy and its Cloudflare Tunnel are dropped.

E4 (2026-11-01) still applies: the speech benchmarks B1 to B4 run on GitHub's `ubuntu-24.04-arm` runners, not on this host. The host is for the release candidate and production (#112), and for the end-to-end checks and actual-server performance gates that tracker #155 keeps open.

The design assumes **4 cores and 16 GB** (Architecture 11; System Design 2.2 and 5.2; `deploy.md` first-time setup step 1). That gives roughly 150 learners a day at stage 0.

## Decision

1. **The stage 0 and production host is a Hostinger KVM 4 VPS** in Hostinger's **France** data center, running Ubuntu 26.04.1 LTS (x86_64), with Docker Engine and Compose from Docker's apt repository. It is the one Compose VM of ADR 0066. Nothing in `compose.prod.yml` or the deploy scripts is specific to Hostinger.
2. **Observed on 2026-11-23** (full record in the runbook): 4 vCPUs (AMD EPYC 9354P under KVM, 1 thread per core), 15.6 GiB of memory, no swap, a 200 GB disk, cgroup v2 with the systemd driver, Docker Engine 29.10.0, Compose v5.8.0 and buildx 0.39.1. The container limits, seccomp and the isolated internal bridge that ADR 0049 needs all work. It matches the design's 4-core, 16 GB target, so System Design 2's capacity arithmetic applies unchanged. It still needs the real-load measurements under #155.
3. **Cost: USD 114 for 12 months, paid yearly, which is USD 9.50 a month** (owner-stated, 2026-11-23). The renewal price was not given; the owner confirms it before the term ends.
4. **Size the media worker to the host with a host override, not by editing `compose.prod.yml`.** The repository's `worker-media` limit (`mem_limit: 18g`, ADR 0049) is more than the host's 15.6 GiB, and the host has no swap. The host's `/opt/listenup/compose.host.yml`, which `deploy.sh` already loads and which is never in the repository, sets `mem_limit: 12g` and `memswap_limit: 12g`. `cpus: 2` stays. The runbook gives the file and the arithmetic. The values are a starting point until #112 measures peak memory with the real models.
5. **x86_64, not Arm.** The release images are already multi-platform (ADR 0071), so the amd64 images run as they are. The Arm-specific follow-ups of ADR 0073 (#231, #232) matter only for E4's Arm benchmark runners, not for this host.

## Consequences

### NFR-AI-3 is no longer met for hosting

NFR-AI-3 says the MVP runs on free tiers or open-source models "with no paid service required". The host is now a **paid service at USD 9.50 a month** (USD 114 a year). The AI side is unchanged: speech runs on self-hosted open-source models, and hosted text AI stays free-tier and disabled by default (ADR 0037). Hosting is the only paid part. This is a known, owner-approved deviation (E6), not an oversight. The SRS and Architecture 11 ("one free virtual machine") still say free. They must be changed by a pull request to `docs/design/` (with #234), or NFR-AI-3 narrowed to AI providers. That needs the owner's decision and is not made here.

### Shared vCPUs: CPU steal

A KVM VPS shares its physical cores with other tenants. `lscpu` shows a KVM guest and does not say whether the vCPUs are dedicated, and the Hostinger plan does not promise that they are. If neighbours are busy, the hypervisor takes time from our vCPUs ("steal", the `st` column of `vmstat`). Speech jobs are CPU-bound and sized in core-seconds (System Design 2.2), so steal shows up directly as slower transcription and Shadow grading, and as fewer learners a day.

- **Baseline:** `vmstat 5 12` on 2026-11-23 showed `st` = 0 in all 12 samples. The host was idle, so this says nothing about steal under load.
- **How it is watched until there is a metric:**
  - Run `vmstat 5 60` and record the `st` column:
    - during the first real media jobs after #112's cutover;
    - during each #155 performance run;
    - once a week as part of the runbook's weekly check.
  - A performance result is valid only together with the steal reading from the same run.
- **Thresholds:**
  - Average `st` above **5%** over a 5-minute sample under load: record it and re-measure.
  - Above **10%** sustained for an hour, or recurring on most weekly checks: raise it with Hostinger support and ask the owner whether to move to a dedicated-CPU plan or another provider. Moving is a configuration change (deploy.md, "Rebuilding the server elsewhere").
- **Follow-up (not in this change):** export host CPU time by mode, including steal, to the Prometheus stack (ADR 0031), with an alert at the 10% threshold. Today the stack has no host-level CPU metric. This belongs with #112's monitoring step or a new issue.

### Other consequences

- **Privacy texts.** Learner data handled on the host (uploads in transit, the media worker's scratch space, logs) is processed by Hostinger in France (EU). The privacy drafts in `docs/legal/` must name the provider and region before launch. The proposed wording is in this change's pull request. Consent versions do not change here. The managed database, storage and email providers are still unchosen (ADR 0066).
- **Hostinger's own agent.** The image carries Hostinger's Monarx apt source (a malware scanner). Whether the agent runs, and what it reads, was not checked. The owner should review it before learner data reaches the host.
- **Host key.** The SSH host key accepted on 2026-11-23 was the one already in the owner's `known_hosts`. The owner compared its ED25519 fingerprint with the one in Hostinger's browser terminal the same day, and they match. #112 can use it for `DEPLOY_SSH_KNOWN_HOSTS`.
- **OS.** Ubuntu 26.04 differs from the 24.04 that ADR 0073, `provision-host.sh` and the runbooks assumed. Docker's repository and `provision-host.sh` use the OS codename, so nothing breaks. `provision-host.sh` (run in #112, not here) adds a 4 GB swap file by default. With the override's `memswap_limit` equal to `mem_limit`, the media worker still never swaps.
- **Still open:** web ports, the firewall, the `deploy` user, secrets, DNS and the first deploy stay with #112. The actual-server performance criteria stay **deferred until staging — unverified** under #155.
