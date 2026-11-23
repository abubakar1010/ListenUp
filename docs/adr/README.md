# Architecture decision records

Each file records one decision: its context, the decision and its consequences. ADRs 0001 to 0011 come from the [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13). Add a new numbered file for every significant decision; to change a decision, add a new ADR that supersedes the old one and update the old one's status.

## Numbering

Three numbers were used twice and are kept as they are; do not renumber any ADR, because other documents link to the files by name:

- 0039: [Google OIDC and deletion confirmation](0039-google-oidc-and-deletion-confirmation.md) and [performance validation before launch](0039-performance-validation-before-launch.md)
- 0052: [admin usage through a separate read-only connection](0052-admin-usage-through-a-separate-readonly-connection.md) and [ai-evals runner and report format](0052-ai-evals-runner-and-report-format.md)
- 0057: [Shadow segment proposals](0057-shadow-segment-proposals.md) and [uniform sign-in lockout](0057-uniform-sign-in-lockout.md)

A fourth duplicate, 0092, was found after both #82 and #90 merged. #119 had assigned 0092 and 0093 to #82, so [provisional Shadow delivery scores](0092-provisional-shadow-delivery-scores.md) keeps 0092, and #90's decision was renumbered once, by owner decision, to [ADR 0100: deleting a practice session or one Shadow recording](0100-session-and-recording-deletion.md). Every link in the repository was updated with it. The rule above still holds for 0039, 0052 and 0057.

Some numbers were reserved for parallel sessions and never used. They stay unused for good, so that a link or a branch from the time they were reserved cannot point to a different decision:

- 0075 to 0079
- 0081 to 0084
- 0088 to 0091

Do not take a new number from "the highest number on `main` plus 1". Sessions run in parallel, and each takes its numbers only from the range named in its prompt, and the owner records the assignments in the [backlog index (#119)](https://github.com/abubakar1010/ListenUp/issues/119). The session prompt is authoritative if it differs from the index; the index records the assignments and does not grant a range absent from the prompt. Before using a number, check that no open pull request or unmerged branch already has a file with it. A session whose prompt names no range adds no ADR; it stops and asks the owner for one before proceeding with work that requires a new ADR. Significant decisions still require an ADR under `CLAUDE.md` and `docs/workflow.md`.

The branch `docs/16-stage-zero-benchmark-host` adds `0067-stage-zero-host-eligibility-and-provisioning-gate.md`. That number is already taken on `main` by [mark tags](0067-mark-tags.md), and the proposed stage 0 host decision is [ADR 0073](0073-stage-0-host-oracle-always-free-arm.md). Do not merge that branch or copy its ADR as it is.
