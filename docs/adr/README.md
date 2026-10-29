# Architecture decision records

Each file records one decision: its context, the decision and its consequences. ADRs 0001 to 0011 come from the [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13). Add a new numbered file for every significant decision; to change a decision, add a new ADR that supersedes the old one and update the old one's status.

## Numbering

Three numbers were used twice and are kept as they are; do not renumber any ADR, because other documents link to the files by name:

- 0039: [Google OIDC and deletion confirmation](0039-google-oidc-and-deletion-confirmation.md) and [performance validation before launch](0039-performance-validation-before-launch.md)
- 0052: [admin usage through a separate read-only connection](0052-admin-usage-through-a-separate-readonly-connection.md) and [ai-evals runner and report format](0052-ai-evals-runner-and-report-format.md)
- 0057: [Shadow segment proposals](0057-shadow-segment-proposals.md) and [uniform sign-in lockout](0057-uniform-sign-in-lockout.md)

The next free number is the highest number on `main` plus 1. Check open pull requests for numbers they have taken, and when several sessions run in parallel use the range assigned in the session's prompt.
