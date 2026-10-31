# ADR 0073: Stage 0 benchmark host: Oracle Always Free Arm, 2 OCPUs and 12 GB

- Status: Proposed; owner approved the two-core selection, but provisioning and team access remain unverified
- Date: 2026-10-27; owner scope decision recorded 2026-10-29
- Story: [#16](https://github.com/abubakar1010/ListenUp/issues/16) (spike; stays open until the VM exists)
- Requirements: NFR-AI-3 (zero cost); [Software Architecture 11](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 2, 5.2 and 12](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADRs 0028, 0034, 0039 and 0066
- Runbook: [`docs/runbooks/stage-0-host.md`](../runbooks/stage-0-host.md)

## Context

Benchmarks B1 to B4 must run on the stage 0 server, and production is one Docker VM (ADR 0066). The design assumes **4 cores and 16 GB** (Architecture 11; System Design 2.2 and 5.2: two media processes of 2 threads each; `deploy.md` first-time setup step 1), which gives about 150 learners a day. Architecture 11 proposed an always-free Arm VM such as Oracle's and told us to check current limits first.

### Limits checked on 2026-10-27

Historical source inspection from 2026-10-27, preserved below; not re-fetched by
the 2026-10-29 provisioning session and not proof of tenancy-specific eligibility.
The original inspection reported no Oracle page update date, only a 2026 copyright line.

| Offer | What the official page says | Fits the 4-core, 16 GB target? |
| --- | --- | --- |
| **Oracle Cloud Always Free, Ampere A1** ([Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm)) | First 1,500 OCPU-hours and 9,000 GB-hours a month, "equivalent to **2 OCPUs and 12 GB** of memory" for Always Free tenancies, in one instance or two. 200 GB of boot plus block volume combined and 5 volume backups, in the home region. **10 TB a month** outbound. Not available in the South Korea North (Chuncheon) availability domains. Instances must be created in the tenancy's **home region**. | **No.** Half the cores and 12 GB. |
| Oracle idle reclaim (same page) | Idle Always Free compute may be reclaimed if, **over 7 days, all three** hold: CPU at the 95th percentile below 20%, network below 20%, and memory below 20% (the memory test applies to A1 only). | Applies to us when the VM sits idle. |
| Oracle capacity (same page) | An "out of host capacity" error means retry another availability domain, wait, or upgrade the account. Capacity is not guaranteed in any region. | Risk at creation time. |
| **Google Cloud Free Tier** ([free features](https://docs.cloud.google.com/free/docs/free-cloud-features), page dated 2026-10-27) | One non-preemptible `e2-micro` a month in `us-west1`, `us-central1` or `us-east1`; 30 GB-months standard disk; **1 GB** outbound a month from North America. The page states no vCPU or memory (the e2-micro is a 1 GB class machine, not re-checked). Separate Free Trial: $300 credit over 90 days. | **No.** Far too small. The **trial credit** can pay for a larger VM for a few days. |
| **Azure free account** ([Microsoft Learn, 2026-03](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/avoid-charges-free-account)) | $200 credit for the first 30 days, then free services for 12 months (it must be upgraded to pay as you go within 30 days). Search results for the free-account page list 750 hours a month each of B1s, B2pts v2 (Arm) and B2ats v2 burstable VMs; the fetched pages did not, so treat that as unconfirmed. Sizes were not checked. | **No.** Burstable 2-vCPU class and expires after 12 months. |
| **AWS Free Tier** ([aws.amazon.com/free](https://aws.amazon.com/free/)) | Free plan: $100 in credits on sign-up, up to $100 more for tasks, account closes after 6 months or when credits run out. EC2 is listed as available; the page names no instance types. | **No** as a host. Credits could pay for a short 4-vCPU run (instance eligibility unchecked). |

**Oracle cut the free Arm allowance.** Until mid-2026 it was 4 OCPUs and 24 GB. The documentation now says 2 OCPUs and 12 GB. Press and community reports ([InfoQ](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Linuxiac](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/)) date the change to 2026-06-15, with no announcement, and say over-limit instances were shut down until resized. Oracle's own page carries no change note. The same reports disagree about whether pay-as-you-go accounts are billed above the new allowance. **The 2026-10-27 inspection could not check Oracle's pay-as-you-go A1 price** (the price pages return 403), so no price is claimed here.

One Ampere OCPU is one physical core (no SMT), so the approved allocation is
**two cores, not four**, with 12 GB nominal RAM. Record guest-visible RAM and
usable CPU topology/quota rather than assuming nominal resources are available.
This is the owner's approved **initial benchmark host** deviation from #16's
four-core scope and the design's four-core/16 GB assumption. It establishes no
learner capacity, throughput or latency result. The design and performance targets
remain unchanged; neither a 75-learner estimate nor linear transfer from x86 is
accepted evidence. The production media container's `mem_limit: 18g` exceeds this
host's nominal RAM; its equal `memswap_limit: 18g` prohibits container swap.
Host swap cannot resolve that mismatch. Later workload sessions must record their
own reviewed resource budgets; #16 changes no production limits or concurrency.

### Do our images and the speech stack run on arm64?

The original 2026-10-27 package inspection was not a host test. Since then,
[PR #238](https://github.com/abubakar1010/ListenUp/pull/238) and
[PR #239](https://github.com/abubakar1010/ListenUp/pull/239) merged on 2026-10-28.
Their evidence and limitations are recorded in [ADR 0071](0071-multi-arch-release-images-built-with-qemu.md)
and [ADR 0072](0072-parselmouth-wheel-built-in-a-throwaway-stage.md).

| Evidence layer | Current finding and limit |
| --- | --- |
| Image build support | All six Release matrix images declare `linux/amd64,linux/arm64`. Deploy check builds them natively on an Arm CI runner. This resolves the old amd64-only build claim; it does not establish a published release's contents. |
| Parselmouth | Upstream 0.4.7 still lacks a Linux arm64 wheel. The reviewed throwaway toolchain stage now builds it; runtime images omit the compiler. PR #239 records native Arm imports and tone parity. A missing upstream wheel is no longer a repository build blocker. |
| Speech runtime on CI | PR #239 records a limited wav2vec2 int8/fp32 comparison on Arm; it is not model-quality acceptance or actual-host performance. Int8 quality remains for corrected B2/#233. |
| Real Release publication | Not verified by this #16 session. Do not claim that a particular immutable release tag contains working Arm manifests without inspecting that release's run and digests. No Release is dispatched here. |
| Actual-host execution and speed | Unverified: no stage-0 host access exists yet. Neither the development container, QEMU nor the Arm CI runner is the benchmark host. B1–B4, latency, concurrency and capacity need separate real-host evidence. Historical ADR 0034 measurements do not transfer automatically. |
| Base images | Architecture support from maintainers is distinct from pulling and executing on the chosen host. The runbook records only actual smoke-check image digests; application-image verification belongs to a later session. |

## Decision

1. **Owner-approved initial benchmark host:** Oracle Always Free
   `VM.Standard.A1.Flex`, **2 OCPUs, 12 GB nominal RAM**, 100 GB boot volume,
   official Ubuntu 24.04 aarch64 image in the tenancy's home region. Verify the
   account-specific recurring free eligibility, all existing A1/storage allocation,
   networking costs and live capacity before creation. Public documentation alone
   does not establish account eligibility. No tenancy or host is verified yet.
2. **Scope:** provision Docker Engine 28+ and Compose 2.24+, verify team SSH and
   basic container/resource-limit operation, and record observed hardware. This is
   a benchmark-host decision, not production deployment approval. Do not configure
   a production deploy key, application secrets or automatic deployment.
3. **Benchmark scope:** later sessions may measure feasibility on these two cores.
   Preserve all existing performance targets and clearly report the smaller host.
   Do not claim four-core capacity, change workload settings silently, or infer
   production suitability from a generic Docker smoke check. #17 video measurements
   and B1–B5 are outside this provisioning session.
4. **Fallback:** if account eligibility or A1 capacity fails, retry another
   availability domain in the home region or wait. If still unavailable, stop and
   ask the owner to select a separately authorized host. No other qualifying
   always-free host was established by the historical comparison above. Paid VMs,
   account upgrades and trial credits are **not authorized**. The old trial-credit
   four-core proposal is withdrawn; any future alternative requires explicit
   approval and a decision record before provisioning.
5. **Reclamation:** record an owner and recovery route. Oracle may reclaim idle
   resources under its published criteria. Do not generate artificial load to
   evade reclamation or assume loaded model memory prevents it.

## Completion and follow-ups

- Accept this ADR only after a real host exists, team SSH access is verified,
  Docker/resource checks pass and the [runbook inventory](../runbooks/stage-0-host.md#5-host-inventory)
  contains observed evidence. Selection approval alone does not accept the ADR.
- Keep #16 open until its revised two-core acceptance criteria are satisfied:
  a team-reachable VM with verified Docker/Compose, documented actual resources,
  current limits and fallback, and the reviewed host record/ADR merged by the owner.
- #231/#232 build support landed in PRs #238/#239. Real Release evidence and
  actual-host application/model checks remain separate. #233 owns real-host
  speech measurements; #234 owns broader design reconciliation. This record
  changes no design performance targets.
- #17 remains blocked until host provisioning/access/checks succeed. No video
  measurements, YouTube intake, production deployment (#112) or launch validation
  (#155) are performed by #16. A documentation-only PR cannot complete #16.

## Provisioning observation — 2026-10-29

At baseline `86133c5`, the managed environment reported current observations,
HTTP policy enforced, and no secret bindings, runtime variables or outbound cloud
identities. OCI CLI/profile, SSH config/known-hosts and SSH agent were absent;
no authorized host endpoint was supplied. The TCP policy has no destination
grants. Repository access works but provides no OCI tenancy authorization.
No cloud create call, remote SSH, package installation or host smoke check was
attempted. Account eligibility, region, capacity and team reachability are unknown.
The owner chose the Oracle Console/local-verification route on 2026-10-29.
Results are pending; this does not confirm an instance exists.
See the runbook for numbered owner actions and pending inventory. These are access
blockers, not evidence that Oracle rejected the account or lacked capacity.

## Sources checked on 2026-10-27

- Oracle, [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (limits, reclaim rule, home region, capacity advice; no update date on the page).
- Google Cloud, [Free features](https://docs.cloud.google.com/free/docs/free-cloud-features) (last updated 2026-10-27).
- Microsoft, [Avoid charges with your Azure free account](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/avoid-charges-free-account) (updated 2026-03).
- AWS, [Free Tier](https://aws.amazon.com/free/) (no date on the page).
- Reports of Oracle's cut: [InfoQ, July 2026](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Linuxiac](https://linuxiac.com/oracle-quietly-cuts-free-tier-ampere-a1-resources-in-half/). Secondary sources; the limit itself is from Oracle's page.
- PyPI JSON for `praat-parselmouth`, `ctranslate2`, `onnxruntime`, `av`, `tokenizers`, `numpy`; the PyTorch CPU wheel index; `apps/api/uv.lock`.
- Not obtained: Oracle's pay-as-you-go A1 price (403), Azure's free VM sizes, AWS's eligible EC2 types.
