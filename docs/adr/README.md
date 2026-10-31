# Architecture decision records

Each file records one decision: its context, the decision and its consequences. ADRs 0001 to 0011 come from the [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13). Add a new numbered file for every significant decision; to change a decision, add a new ADR that supersedes the old one and update the old one's status.

## Numbering

Three numbers were used twice and are kept as they are; do not renumber any ADR, because other documents link to the files by name:

- 0039: [Google OIDC and deletion confirmation](0039-google-oidc-and-deletion-confirmation.md) and [performance validation before launch](0039-performance-validation-before-launch.md)
- 0052: [admin usage through a separate read-only connection](0052-admin-usage-through-a-separate-readonly-connection.md) and [ai-evals runner and report format](0052-ai-evals-runner-and-report-format.md)
- 0057: [Shadow segment proposals](0057-shadow-segment-proposals.md) and [uniform sign-in lockout](0057-uniform-sign-in-lockout.md)

Some numbers were reserved for parallel sessions and never used. They stay unused for good, so that a link or a branch from the time they were reserved cannot point to a different decision:

- 0075 to 0079
- 0081 to 0084
- 0088 to 0091

Do not take a new number from "the highest number on `main` plus 1". Sessions run in parallel, and each takes its numbers only from the range assigned to it in the [backlog index (#119)](https://github.com/abubakar1010/ListenUp/issues/119), as named in the session's prompt. A session without an assigned range adds no ADR; it stops and asks the owner for one.

The branch `docs/16-stage-zero-benchmark-host` adds `0067-stage-zero-host-eligibility-and-provisioning-gate.md`. That number is already taken on `main` by [mark tags](0067-mark-tags.md), and the stage 0 host decision is [ADR 0073](0073-stage-0-host-oracle-always-free-arm.md). Do not merge that branch or copy its ADR as it is.
