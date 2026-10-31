# #16 stage-0 provisioning record — blocked

Checked 2026-10-29 (Asia/Dhaka). Baseline: `86133c5` on current `main`.
Branch: `docs/16-stage-zero-host-provisioning-record`.

## Scope and ownership

- Read `CLAUDE.md`, `AGENTS.md`, workflow/testing policy, Deployment and Media
  sandbox conventions, Architecture §11, System Design §2/12, ADR 0073 and the
  stage-0 runbook; checked current resource limits and Arm build configuration.
- #16 is open with no comments. Open/merged PR and branch searches found the
  merged proposal #230, Arm support #238/#239, and ADR renumbering #240.
- Inspected `docs/16-stage-zero-benchmark-host` read-only: head `f087b34`, one
  commit ahead and 144 behind current main, no PR found. It records an earlier
  blocked four-core recommendation, not a verified host. No active owner was
  confirmed; absence of a PR was not treated as abandonment. Left it untouched.
- PR #249 belongs to another review session. It was not reviewed and its branch
  was not checked out or modified.
- Initial local-only `work` branch failed the naming validator. Renamed it to the
  unused compliant branch above before edits. The clean starting HEAD matched
  current main; no worktree was created.
- Owner approved the plan and selected Console creation/local verification.
  The approved initial host is **Oracle Always Free A1, 2 OCPUs / 12 GB**, an
  explicit deviation from #16's original four-core target. No performance target,
  production resource limit, concurrency setting or design document was changed.

## Access observation and blocker

Managed runtime: current observations, connected, HTTP policy enforced; zero
configured secret bindings, runtime variables or outbound cloud identities.
Non-secret presence checks found no OCI CLI/profile, SSH config/known-hosts,
SSH agent or supplied host endpoint. The TCP policy has no destination grants.
GitHub access succeeded; no OCI API or host SSH call was attempted.

This establishes missing access in the session, not account rejection or lack of
Oracle capacity. The owner will create the VM and run the documented checks
locally; no eligibility confirmation, instance state, inventory or verification
output has yet been returned. No infrastructure resource was created, package
installed on a remote host, or Docker host check executed by this session.

Next owner actions and exact non-secret confirmations are in
[runbook step 1](../runbooks/stage-0-host.md#1-owner-actions-to-unblock-access).
Return sanitized results for [the host inventory](../runbooks/stage-0-host.md#5-host-inventory),
including separate team SSH checks. Do not send private keys/passwords/API secrets.
Paid resources, upgrades and credits remain unauthorized.

## Acceptance mapping

| Criterion | Required evidence/check | Observed result |
| --- | --- | --- |
| Approved two-core VM exists and is team reachable | Account eligibility, instance facts, trusted host fingerprint, each intended operator's separate SSH success/timestamp | Blocked; owner Console/local verification pending |
| Docker works on actual host | Server Engine >=28, Compose >=2.24, hello-world architecture/digest | Not run |
| Actual resources and limits recorded | CPU model/topology/quota, RAM, swap, disk, OS/kernel/cgroup, CPU/memory/swap/pids/seccomp/isolated-bridge checks | Not run; inventory pending |
| ADR records scope, dated limits and fallback | ADR 0073 manual comparison with owner decision, current production limits and merged Arm support | Prepared; remains Proposed; historic provider comparison clearly dated, account checks pending |
| One verified host record PR | Observed inventory plus accepted ADR after successful host/team checks | Draft documentation preparation only; #16 incomplete |
| #17 handoff | Host/access/resource gates above pass | **Blocked; host not ready**, no video measurements started |

## Documentation validation

Only Markdown changes. TDD does not apply under `docs/testing.md` because no
executable behavior changes; no artificial failing test or retrospective red/green
claim is made. The shell blocks are operator instructions, syntax-checked only.
No backend, web, schema, API, infrastructure script or workflow changes; application
suites, application changed-line coverage and media sandbox execution are not
applicable to this documentation diff. CI and independent fresh-session review
remain required before owner merge.

Checks run from the repository root:

- `bash .github/scripts/check-branch-name.sh "$(git branch --show-current)"`: passed
  on the new branch.
- `git diff --check`: passed.
- Local Markdown validation: relative file links resolve; fences balance; new
  inventory anchors match their headings. See the PR for final counts.
- Each of the three `sh` blocks in `stage-0-host.md` passed `bash -n` via stdin.
  Commands were not executed on the development container or a benchmark host.
- Manual source comparison: Release's six matrix images include both platforms;
  Deploy check has the native Arm job/cache; Dockerfile has the throwaway wheel
  stage and `--no-install-package praat-parselmouth`. This is repository inspection,
  not a new build or proof of real Release publication or actual-host performance.

No production deployment, automatic deployment, YouTube intake, #17 measurement,
B1–B5 run or merge was performed. Keep #16 open and ADR 0073 Proposed until the
missing evidence is obtained; documentation alone is not completion.
