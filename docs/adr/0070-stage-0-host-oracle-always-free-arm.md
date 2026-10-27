# ADR 0070: Stage 0 host: Oracle Cloud Always Free Arm VM, with a trial-credit VM for the 4-core measurements

- Status: Proposed (becomes Accepted when the owner has provisioned the VM and recorded its facts, see the runbook)
- Date: 2026-10-27
- Story: [#16](https://github.com/abubakar1010/ListenUp/issues/16) (spike; stays open until the VM exists)
- Requirements: NFR-AI-3 (zero cost); [Software Architecture 11](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 2, 5.2 and 12](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADRs 0028, 0034, 0039 and 0066
- Runbook: [`docs/runbooks/stage-0-host.md`](../runbooks/stage-0-host.md)

## Context

Benchmarks B1 to B4 must run on the stage 0 server, and production is one Docker VM (ADR 0066). The design assumes **4 cores and 16 GB** (Architecture 11; System Design 2.2 and 5.2: two media processes of 2 threads each; `deploy.md` first-time setup step 1), which gives about 150 learners a day. Architecture 11 proposed an always-free Arm VM such as Oracle's and told us to check current limits first.

### Limits checked on 2026-10-27

Official pages, fetched today. None of Oracle's pages shows an "updated" date, only a 2026 copyright line.

| Offer | What the official page says | Fits the 4-core, 16 GB target? |
| --- | --- | --- |
| **Oracle Cloud Always Free, Ampere A1** ([Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)) | First 1,500 OCPU-hours and 9,000 GB-hours a month, "equivalent to **2 OCPUs and 12 GB** of memory" for Always Free tenancies, in one instance or two. 200 GB of boot plus block volume combined and 5 volume backups, in the home region. **10 TB a month** outbound. Not available in the South Korea North (Chuncheon) availability domains. Instances must be created in the tenancy's **home region**. | **No.** Half the cores and 12 GB. |
| Oracle idle reclaim (same page) | Idle Always Free compute may be reclaimed if, **over 7 days, all three** hold: CPU at the 95th percentile below 20%, network below 20%, and memory below 20% (the memory test applies to A1 only). | Applies to us when the VM sits idle. |
| Oracle capacity (same page) | An "out of host capacity" error means retry another availability domain, wait, or upgrade the account. Capacity is not guaranteed in any region. | Risk at creation time. |
| **Google Cloud Free Tier** ([free features](https://docs.cloud.google.com/free/docs/free-cloud-features), page dated 2026-10-27) | One non-preemptible `e2-micro` a month in `us-west1`, `us-central1` or `us-east1`; 30 GB-months standard disk; **1 GB** outbound a month from North America. The page states no vCPU or memory (the e2-micro is a 1 GB class machine, not re-checked). Separate Free Trial: $300 credit over 90 days. | **No.** Far too small. The **trial credit** can pay for a larger VM for a few days. |
| **Azure free account** ([Microsoft Learn, 2026-03](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/avoid-charges-free-account)) | $200 credit for the first 30 days, then free services for 12 months (it must be upgraded to pay as you go within 30 days). Search results for the free-account page list 750 hours a month each of B1s, B2pts v2 (Arm) and B2ats v2 burstable VMs; the fetched pages did not, so treat that as unconfirmed. Sizes were not checked. | **No.** Burstable 2-vCPU class and expires after 12 months. |
| **AWS Free Tier** ([aws.amazon.com/free](https://aws.amazon.com/free/)) | Free plan: $100 in credits on sign-up, up to $100 more for tasks, account closes after 6 months or when credits run out. EC2 is listed as available; the page names no instance types. | **No** as a host. Credits could pay for a short 4-vCPU run (instance eligibility unchecked). |

**Oracle cut the free Arm allowance.** Until mid-2026 it was 4 OCPUs and 24 GB. The documentation now says 2 OCPUs and 12 GB. Press and community reports ([InfoQ](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Linuxiac](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/)) date the change to 2026-06-15, with no announcement, and say over-limit instances were shut down until resized. Oracle's own page carries no change note. The same reports disagree about whether pay-as-you-go accounts are billed above the new allowance. **We could not check Oracle's pay-as-you-go A1 price today** (the price pages return 403), so no price is claimed here.

One Ampere OCPU is one physical core (no SMT), so 2 OCPUs are 2 cores. The free VM therefore has **half the compute** the design assumed (about 75 learners a day by System Design 2.2's arithmetic, which is linear in cores) and **12 GB**, below the 16 GB in `deploy.md`. The media worker's `mem_limit: 18g` in `compose.prod.yml` also exceeds the VM's memory and needs a host override.

### Do our images and the speech stack run on arm64?

Checked against PyPI, the PyTorch CPU index and the repository today. No arm64 machine or Docker daemon was available in this session, so **nothing below was run on arm64**.

| Piece | Finding |
| --- | --- |
| `faster-whisper` 1.2.1 | Pure Python (`any` wheel). |
| `ctranslate2` (locked 4.8.2) | `manylinux_2_27/2_28_aarch64` wheel on PyPI. |
| `onnxruntime`, `av`, `tokenizers`, `numpy`, `psycopg-binary`, `pydantic-core`, `uvloop`, `cryptography` | Linux aarch64 cp312 wheels in `uv.lock` or on PyPI. |
| `torch` and `torchaudio` (CPU index, `>=2.4,<2.9`) | cp312 `aarch64` wheels exist for 2.4.1 and 2.8.0 (torch) and 2.4.0 to 2.8.0 (torchaudio). |
| **`praat-parselmouth` 0.4.7** | **No Linux arm64 wheel in any release** (0.4.0 to 0.4.7, the latest). Only macOS arm64, Linux x86_64 and i686, Windows. The locked sdist builds with CMake and scikit-build. `uv sync --frozen --extra speech` in `backend.Dockerfile` will compile it from source on arm64, which needs a C++ toolchain and CMake that the `python:3.12-slim` base lacks. Whether it compiles, how long it takes and whether results match x86 are **unverified**. |
| wav2vec2 dynamic int8 (`quantize_dynamic`, `wav2vec2_ctc.py`) | PyTorch's quantized engine differs on Arm (QNNPACK rather than FBGEMM). Untested; accuracy and speed must be re-measured. |
| Base images (`python:3.12-slim`, `node:22-alpine`, `caddy:2.10.2-alpine`, `haproxy:3.2.4-alpine`), Debian `ffmpeg`, `clamav`, pgdg `postgresql-client-16` | Published for arm64 by their maintainers; not re-inspected here (the runbook has the commands). |
| **Our release workflow** | `release.yml` builds each image once, on an `ubuntu-latest` (x86_64) runner, with no `platforms` setting. **The images are amd64 only and will not start on an Arm host** ("exec format error"). |
| Model speed | The speeds in ADR 0034 (0.54 core-s per audio-s for `small.en` int8) are not Arm numbers. B1 to B4 are measured per core-second, so they transfer to a 2-core run; they must be re-run on this VM anyway, which is the point of the spike. |

## Decision

1. **Chosen host: an Oracle Cloud Always Free `VM.Standard.A1.Flex` instance using the whole free allowance: 2 OCPUs, 12 GB memory, a 100 GB boot volume, Ubuntu 24.04 aarch64, one public IPv4 address, in the tenancy's home region.** It is the only always-free VM found that can run the speech models at all, it keeps the MVP at zero cost (NFR-AI-3), and its 10 TB of egress is far above need. It does **not** meet the 4-core target; that is a known deviation, not an oversight.
2. **Size the stack to the host.** One media process of 2 threads (not two processes), `mem_limit` for `worker-media` lowered in the host's `compose.host.yml`, and a swap file as a safety net. The runbook gives starting values; the benchmarks decide the real ones.
3. **Run B1 to B4 on this VM** (per-core results transfer) and **run B5 and the capacity commitments in System Design 2 on a short-lived 4-vCPU, 16 GB VM bought with trial credit** (Google Cloud's $300 over 90 days, or AWS's $100 to $200 over 6 months), deleted when the run ends. It costs nothing if the credit is available. If B1 to B4 on the free VM show the 2-core stage 0 is enough for the launch audience, the 4-core run only needs B5.
4. **Fallback host, in order:**
   1. **Oracle capacity or account trouble** (out of host capacity in every availability domain, a rejected sign-up, or a reclaimed instance): retry other availability domains over a few days; if it still fails, ask the owner whether to upgrade to pay as you go (Oracle says Always Free resources stay free; reports disagree about A1 above the allowance, so read the billing page first).
   2. **No free Arm VM is possible**: no other always-free VM found fits, so the fallback is the smallest **paid** VM with at least 4 vCPU and 16 GB (Arm or x86). Its price was not checked here. This changes NFR-AI-3's spirit and needs an explicit owner decision and an ADR superseding this one. An x86 host removes the arm64 work below.
5. **Idle reclaim.** The VM holds the loaded speech models (about 1.3 GB, preloaded) plus Postgres-free containers, so memory use may stay above 20%, but CPU and network will be low between benchmarks. All three must be under 20% at once for the reclaim rule, but we have not observed this host, so the runbook records memory use and sets a weekly check. Do not rely on a keep-alive load generator; if reclaim becomes a risk, the owner decides on a pay-as-you-go upgrade.

## Required follow-ups (not in this change)

These are code changes outside a documentation spike. Without the first, the Arm host cannot run a release.

1. **Multi-arch release images**: build `linux/arm64` (native `ubuntu-24.04-arm` runner or QEMU, whichever is available for this repository) for all six images and publish one manifest per tag, keeping the existing `sha-` and `r<n>` tags. Amd64 stays so the same images run in CI and locally.
2. **Parselmouth on arm64**: add a build stage with a C++ toolchain and CMake for `worker-media` (or ship a wheel we build), and confirm `import parselmouth` and the acoustics tests pass on arm64.
3. **Re-measure on the host**: B1 to B4, with wav2vec2 int8 checked against fp32 on Arm; amend ADR 0034's "indicative" numbers.
4. **Update the design documents by pull request** (4 cores and 150 learners become the measured stage 0 figures; the source of truth is `docs/design/`), `docs/runbooks/deploy.md` step 1, and this ADR's status once the VM exists.

## Consequences

- Stage 0 capacity is about half the design figure until a 4-core machine is used, which is acceptable for a pre-launch benchmark host and is stated in the benchmark results.
- The 12 GB host also runs Caddy, the API, the default worker, the signature updater, ClamAV scans and the relay next to the media worker. PostgreSQL and storage stay managed (ADR 0066), so they cost no VM memory; for B1 to B4 a local PostgreSQL container may be used temporarily.
- SSH from GitHub's runners needs port 22 reachable from the internet (GitHub's address ranges are large and change), so the firewall cannot be limited to the owner's address for deploys; the runbook uses key-only login and an optional non-standard port.
- This ADR becomes **Accepted** only after the owner has created the account and VM and pasted the host facts (CPU model, cores, memory, disk, `uname -m`, Docker versions, cgroup version) into the runbook's record. If Oracle capacity or the account fails, a new ADR picks the fallback.

## Sources checked on 2026-10-27

- Oracle, [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (limits, reclaim rule, home region, capacity advice; no update date on the page).
- Google Cloud, [Free features](https://docs.cloud.google.com/free/docs/free-cloud-features) (last updated 2026-10-27).
- Microsoft, [Avoid charges with your Azure free account](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/avoid-charges-free-account) (updated 2026-03).
- AWS, [Free Tier](https://aws.amazon.com/free/) (no date on the page).
- Reports of Oracle's cut: [InfoQ, July 2026](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Linuxiac](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/). Secondary sources; the limit itself is from Oracle's page.
- PyPI JSON for `praat-parselmouth`, `ctranslate2`, `onnxruntime`, `av`, `tokenizers`, `numpy`; the PyTorch CPU wheel index; `apps/api/uv.lock`.
- Not obtained: Oracle's pay-as-you-go A1 price (403), Azure's free VM sizes, AWS's eligible EC2 types.
