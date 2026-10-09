# ListenUp instructions for Codex

Before working, read `CLAUDE.md` for shared project, architecture, command and
commit rules, and `docs/workflow.md` for the story, planning and review process.
Read the relevant section of `docs/conventions.md` before changing an area.
These files apply to both Codex and Claude Code; keep shared rules there rather
than duplicating them here.

- Design documents in `docs/design/` are the source of truth. Read only the
  sections needed by the acceptance criteria. Record changed decisions with
  their ADR; report conflicting requirements rather than choosing policy.
- Use the existing checkout in an isolated cloud task. Do not create a Git
  worktree unless the owner requests one. Start from current `main` for a new
  story; use its existing branch when addressing an open PR.
- At the start of every session, check the current branch before editing. Branch
  names must follow the mandatory naming policy in `CLAUDE.md`: a change-type
  prefix and a readable, auditable kebab-case purpose. Never use a tool name,
  random identifier, or generated adjective as the branch's identity. Rename an
  invalid local-only branch before work; stop and report an invalid pushed or PR
  branch rather than continuing under it.
- If the owner names a compliant branch, use it. Otherwise create one unused,
  compliant branch for the story and report its name. Do not reuse a branch from
  an unrelated PR.
- For complex stories, present the short plan and wait for owner approval before
  editing code. A story prompt that explicitly says "Plan first: no" controls
  that task. Do not treat silence as approval.
- Read a relevant `.claude/agents/*.md` file when using its specialist guidance.
  Those files are instructions, not automatically installed Codex agents or
  skills. Use available file-reading/editing tools in the actual checkout;
  Claude-specific tool names or historical checkout paths are not prerequisites.
  Do not spawn helpers unless the owner explicitly requests delegation.
- Codex does not automatically execute `.claude/settings.json` hooks. Follow
  the cloud environment's saved installation/startup instructions and verify
  the required services and dependencies before running checks.
- Review a PR in a fresh session using the review prompt in `docs/workflow.md`.
  Report findings first; do not edit or merge during a review-only task.
- Follow the commit authorship and Conventional Commit rules in `CLAUDE.md`.
  Open a PR when requested by the task or its explicit "Done means one PR"
  instruction. Fix findings in that PR; the owner merges.
