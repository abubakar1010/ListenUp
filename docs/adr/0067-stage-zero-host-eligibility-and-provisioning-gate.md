# ADR 0067: Stage-0 host eligibility and provisioning gate

- Status: Proposed; provisioning blocked, #16 remains open
- Checked: 2026-10-27 (Asia/Dhaka; 2026-10-26 UTC)
- Story: [#16](https://github.com/abubakar1010/ListenUp/issues/16)
- Requirements: NFR-AI-3; Architecture 11; System Design 2, 5.2 and 12
- Baseline: `main` at `c7975df6de4d0903d46a30af4df6d6dd1bee41e5`

## Decision

No reviewed public cloud offer currently establishes an always-free host meeting
the unchanged four-core target and the current stack's resource envelope.
Do not provision a smaller machine and call #16 complete, or use trial credits as
evidence of continuing zero cost.

Recommended configuration: a dedicated Linux amd64 VM, four sustained CPU cores
(record vCPU/core topology), 24 GiB RAM, 80 GiB SSD, Ubuntu 24.04 LTS, Docker Engine
28+ and Compose plugin 2.24+. Prefer an existing owner/team-funded machine with
explicit permission and confirmed zero incremental hosting cost. No such host is
identified or verified in this session. This is a configuration recommendation,
not an accepted provider or a claim that a host exists.

Conditional cloud fallback: OCI `VM.Standard.A1.Flex`, four OCPUs, 24 GB RAM,
80 GB boot volume in the tenancy's home region, **only** after the owner proves
that this tenancy receives that recurring allowance without credits or charges,
and an Arm-native image/model validation resolves the blockers below. Otherwise
there is no qualifying free fallback among the reviewed offers. A paid host or
reduced benchmark target requires a separate owner decision; neither is selected.

## Official provider comparison

Sources were opened on the checked date. Public eligibility, account quota and
live regional capacity are separate facts; the latter two remain unverified.

| Candidate | Current official evidence | Suitability and availability |
| --- | --- | --- |
| OCI A1, Arm | [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm): 1,500 OCPU-hours and 9,000 GB-hours/month, equivalent to 2 OCPUs/12 GB; 200 GB combined boot/block storage and five volume backups; home region only; 10 TB outbound/month | Insufficient for four cores and the 18 GiB media ceiling. Capacity can be unavailable; try another availability domain in the home region or wait. Never substitute a paid shape. |
| OCI A1, conflicting allowance | [Arm overview](https://docs.oracle.com/en-us/iaas/Content/Compute/References/arm.htm) still states 3,000 OCPU-hours/18,000 GB-hours | Four OCPUs/24 GB for a 744-hour month uses 2,976/17,856 hours. The lower allowance covers only 375 hours at 4/24. Do not infer grandfathering or eligibility from the older page or an instance's free-eligible label. |
| OCI AMD micro, amd64 | Same Always Free resource page: two instances, each 1/8 OCPU with bursting and 1 GB RAM | Cannot combine them into the required single four-core speech host. |
| Google Compute Engine, amd64 | [Free program](https://docs.cloud.google.com/free/docs/free-cloud-features#compute): one non-preemptible e2-micro month's hours across us-west1/us-central1/us-east1, 30 GB-month standard disk, 1 GB outbound to eligible destinations. [Machine pricing](https://cloud.google.com/products/compute/pricing/general-purpose): 1 GiB and 0.25 sustained vCPU, two visible vCPUs | Insufficient RAM, sustained CPU and the runbook's 40 GB disk minimum. Account eligibility, IP/network charges and regional capacity unverified; no zero-cost full host claim. |
| AWS EC2, amd64 or Arm by instance | [EC2 free-tier rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html): new-account plan ends at six months or credit exhaustion; older pre-2025-07-15 accounts have a 12-month offer | Time/credit-limited, unsuitable as an always-free stage-0 commitment. No account or regional capacity verified. |
| Azure VMs, amd64 or Arm by size | [Free services](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/create-free-services): first-month credit, then selected B1S/B2pts v2/B2ats v2 VM allowances up to 750 hours/month within the first 12 months | Time-limited, not a continuing zero-cost solution. Region/size quota and disk/network eligibility require account checks. |

OCI may reclaim idle instances after seven days when its CPU, network and (A1)
memory criteria are all below 20%. Do not generate artificial load to avoid
reclamation. Record recovery ownership. See the linked resource page for details.

## Requirements checked against current production files

Read [deployment](../runbooks/deploy.md), [media sandbox](../runbooks/media-sandbox.md),
Architecture 11, System Design 5.2/12, ADRs 0034, 0049, 0050 and 0066, and these
files at the baseline: `infra/compose/compose.prod.yml`,
`infra/docker/backend.Dockerfile`, `apps/api/src/listenup/worker.py`,
`apps/api/src/listenup/ai/ai.yaml`, `apps/api/uv.lock` and
`.github/workflows/release.yml`.

| Resource | Actual configuration and implication |
| --- | --- |
| CPU | Two media slots, one shared intake/speech and one speech-only; speech libraries use two threads. The whole media container has `cpus: 2`, not four dedicated cores. Four host cores leave capacity for API/default workers, scanning, model provisioning, backup, Caddy and HAProxy. Do not change the cap silently to match the historical two-process/two-thread benchmark assumption. Record it in every benchmark. |
| RAM | Media container `mem_limit: 18g`, two jobs with default 8 GiB address-space/RSS limits plus supervisor; `/scratch` is a bounded 2 GiB tmpfs, charged within container memory, not extra disk/RAM. Limits are ceilings, not measured resident usage or reservations. API/default workers, signature updater, backup, relay and edge have no hard memory caps. Model provisioning can overlap other services at startup. 24 GiB is a planning budget (18 GiB media plus 6 GiB headroom), not a measured sufficient peak. |
| Swap | `memswap_limit: 18g` equals `mem_limit`, so media has **no swap allowance** ([Docker semantics](https://docs.docker.com/engine/containers/resource_constraints/)). A host swapfile cannot make 12/16 GiB RAM equivalent to this envelope. Recommend no swap during reproducible benchmarks; record any pre-existing swap and activity. |
| Disk | Runbook minimum is 40 GB; recommend 80 GiB SSD: budget 10 GiB OS/packages, 25 GiB images/build cache and previous release, 5 GiB weights/signatures, 10 GiB fixtures/results/logs and 30 GiB free headroom. These are estimates; measure actual image layers/cache and free space. Keep at least 20 GiB available before image/model work. No local production DB or media bucket is included. |
| Docker/Linux | Engine 28+, Compose 2.24+, cgroup CPU/memory/swap/pids enforcement, seccomp, libseccomp2, internal bridge gateway mode `isolated`, read-only auxiliary mounts. Docker's official [Ubuntu install guide](https://docs.docker.com/engine/install/ubuntu/) supports Ubuntu 24.04 on amd64 and arm64. Package support alone does not establish speech-image compatibility. |
| Other services | Production uses managed PostgreSQL 16, S3 and SMTP, not local SeaweedFS/Mailpit/Postgres. HAProxy relays only DB/S3 to media. Optional 6 GiB Ollama in local Compose is absent from production and disabled/unaccepted in AI configuration; do not include it as a running speech dependency. |

No managed database/storage account was selected or verified here. ADR 0066 also
requires the database administrator to grant BYPASSRLS and CREATEROLE with admin
option, PostgreSQL 16 and verified TLS, plus private S3 buckets with separate
media/backup credentials. Their free quotas, privileges and reachability must be
checked under #112 before cutover; a free compute host does not prove zero cost
for the complete production stack.

The deployment runbook's 16 GB minimum does not cover the full 18 GiB media
ceiling plus the other services. A 16 GB machine might execute measured lighter
workloads, but is not accepted here without resource measurements and an explicit
budget decision. The 24 GiB recommendation preserves existing limits.

## Speech models and architecture

Current configuration is faster-whisper `small.en`, int8, beam 5, VAD, two CPU
threads; alignment is `WAV2VEC2_ASR_BASE_960H`, dynamic int8, 30-second windows,
two threads. Parselmouth supplies reference pitch/intensity. Historical ADR 0034
reports about 1.4 GB transcription and 1.5 GB alignment peaks measured separately,
about 0.85 GB downloaded weights; these are not concurrent production peaks.
System Design's `base.en`/`MMS_FA`/1.3 GB paragraph is stale relative to `ai.yaml`.
MMS_FA is withdrawn, and ADR 0050's research phoneme model is not a production
speech-assessment adapter. Do not install it as an implied production requirement.

ADR 0049's fresh interpreter per job supersedes warm-model reuse: the supervisor
preloads, but each job loads its own needed models. Include cold loads and
supervisor/job overlap in measurements; older spike RAM/latency is indicative.

Architecture assessment:

- `uv.lock` includes CPython 3.12 Linux amd64 and aarch64 wheels for CTranslate2
  4.8.2, PyAV 19.0.1 and ONNX Runtime 1.30.0; faster-whisper 1.2.1 is pure Python.
  Upstream [CTranslate2 hardware support](https://opennmt.net/CTranslate2/hardware_support.html)
  includes Arm, and its [quantization documentation](https://opennmt.net/CTranslate2/quantization.html)
  describes the Arm Ruy backend. Verify `get_supported_compute_types('cpu')` on
  the candidate host; architecture support is not a performance result.
- Official CPU indexes list Python 3.12 Linux aarch64 packages for
  [torch 2.8.0](https://download.pytorch.org/whl/cpu/torch/) and
  [torchaudio 2.8.0](https://download.pytorch.org/whl/cpu/torchaudio/).
  Use a matching pair per the [compatibility guidance](https://docs.pytorch.org/audio/2.8/installation.html).
  The Dockerfile installs `>=2.4,<2.9` outside `uv.lock`; record resolved versions,
  CPU quantization backend and `forced_align` availability. Do not upgrade to 2.9,
  which removes the alignment API used here.
- **Arm build blocker:** [Parselmouth 0.4.7 files](https://pypi.org/project/praat-parselmouth/0.4.7/#files)
  and the lock contain Linux amd64 wheels but no Linux aarch64 wheel. A source
  archive exists, but the base image has no compiler/CMake build toolchain.
  Validate a separately reviewed native source-build solution before accepting
  Arm; do not assume `uv sync --frozen` succeeds there.
- **Release blocker for Arm:** current image jobs use `ubuntu-latest` with no
  Arm runner or `platforms` setting; their default build is Linux amd64.
  Multi-architecture publication and native model/sandbox checks need a separate
  implementation before an Arm host can consume the current release path.
  QEMU emulation is not representative benchmark evidence.

No image build or real-model run was performed in this documentation task.
Host provisioning checks stop before application/model deployment; #112 owns
cutover, with real-stack performance still gated by #155.

## Access and completion evidence

The current managed environment reports current observations, no configured
secrets, runtime variables or outbound cloud identities. Known OCI/AWS/GCP/Azure
profile locations and SSH config are absent; no owner host or SSH endpoint was
provided. GitHub repository access works, but it does not authorize a cloud
tenancy. No cloud create call was attempted, and no VM was provisioned.

Follow [the owner setup checklist and inventory](../runbooks/stage-zero-host.md).
Both #16 acceptance criteria remain unmet: no team-reachable Docker VM has been
verified, and this proposed ADR is not merged. Keep #16 open, including after a
documentation-only merge. Do not describe the managed development container as
the stage-0 host. Hardware, installed versions and SSH access remain pending.

## Documentation validation

Relative Markdown links and code-fence balance checked for all three changed
documents; the three shell examples in the owner checklist passed `bash -n`.
Branch naming and `git diff --check` passed. TDD and application suites are not
applicable to this documentation-only change under `docs/testing.md`; no runtime
files, deployment workflows or resource limits changed. Shell syntax checks do
not establish that installation or host verification succeeded. Fresh-session
review, CI and owner merge remain outstanding.
