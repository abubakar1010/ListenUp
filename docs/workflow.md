# How a story is built

One story, one session, one pull request. The aim is the fewest tokens for work that is right the first time: rework is the most expensive thing a session can do, so quality checks sit where they are cheapest, and every session stays small.

The same process applies to Claude Code and Codex. `CLAUDE.md` holds shared
project rules; `AGENTS.md` makes them discoverable to Codex. A fresh session in
either tool can build or review a story using the prompts below.

## The steps

1. **Ready (owner).** The issue has acceptance criteria and its dependencies are merged. A story whose blocker is open waits; it is not built around the gap.
2. **Plan (complex stories only).** A story that adds a module, changes the data model, or touches security, privacy or AI grading starts with a plan of 10 to 15 lines: files to change, data changes and migration, risks, and the tests that prove each acceptance criterion. The owner approves or corrects it before any code.
3. **Build.** Tests are written with the code. Run only the tests for the area while working; run the full checks once, before opening the pull request (the checklist below). Open one pull request for the story.
4. **CI.** Every push runs the full suites, the image builds and the vulnerability scan. A red build is fixed in the same pull request.
5. **Review.** A fresh session in Claude Code or Codex reviews the pull request using the review prompt below. In Claude Code, `/code-review <number> medium` is available when that command is installed. Its findings and the owner's answers to policy questions are fixed in the same pull request, followed by the affected checks. Re-review material changes; required CI checks must pass before merge.
6. **Merge (owner).** Merge, close the session, and start the next story from `main`.

Run two or three sessions at once on stories that touch different areas. Each has its own branch and pull request, so nothing needs merging by hand.

Each cloud task already has an isolated checkout; use it without creating a
worktree unless the owner asks. Start a new story from current `main` on one
unused branch, or use the owner's named branch. Continue PR fixes on that PR's
branch. Report the branch at the start; never carry unrelated changes into a PR.

Verify setup in the actual environment. Claude Code may run its session-start
hook; Codex follows saved environment installation/startup instructions. Neither
a hook configuration nor a saved script proves services are running. Check the
dependencies, database and storage needed by the story before validation.

## Choosing the model

| Story | Plan step | Claude Code | Codex |
| --- | --- | --- | --- |
| Contained UI, CRUD endpoints, tests, documentation | No | Sonnet | Available coding model, standard/medium reasoning |
| New module or data model change | Yes | Opus to plan, Sonnet to build | Strongest available coding model with high reasoning to plan; standard/medium reasoning to build the approved plan |
| Security, privacy, AI grading, cross-module | Yes | Opus | Strongest available coding model with high reasoning for plan and implementation |
| Review of a pull request | No | Opus | Strongest available coding model with high reasoning, in a fresh session |

These are task recommendations, not automatic model switches or claims that
Claude and Codex models are equivalent. Select a model your account offers;
reasoning controls and labels vary by client. When a control is unavailable,
use the most capable available model for complex work and reviews. Changing
models does not replace plan approval or independent review.

`.claude/agents/` holds reusable specialist guidance (backlog planning, UX, UI
design and document synchronization). Claude Code can use those agent definitions;
Codex can read the relevant file as instructions and apply it with its available
tools. The files do not automatically register Codex agents, skills or slash
commands. Read `.claude/agents/docs-sync.md` when synchronizing design documents.
Keep sessions focused; delegate only when the owner requests it.

## Prompt template for a story session

```
Story: #<number> <title>. Read the issue first.
Tool: <Claude Code or Codex>. Branch: <named branch, or create one from main>.
Area: <module and directories>. Do not change: <areas owned by other open work>.
Plan first: <yes or no>. If yes, stop after the plan and wait for approval.
Read CLAUDE.md and docs/workflow.md; in Codex also follow AGENTS.md.
Read docs/conventions.md for the areas you touch. Read the design documents only
where an acceptance criterion needs them.
Done means every item of the checklist in docs/workflow.md, then one pull request.
Do not merge; the owner merges after fresh-session review and passing CI.
```

## Prompt template for a review session

Start a new session so the reviewer does not inherit the builder's conversation.
It may use either tool; changing tools is optional.

```
Review PR #<number> in abubakar1010/ListenUp against its base branch.
Read CLAUDE.md, docs/workflow.md and the conventions for the changed areas;
in Codex also follow AGENTS.md. Read the issue's acceptance criteria and cited
design sections/ADRs. For design synchronization, read .claude/agents/docs-sync.md.
Check correctness, security, regressions, scope, acceptance criteria and validation.
Report actionable findings with severity, file/line, impact and suggested fix.
List policy contradictions as questions for the owner; do not invent decisions.
Distinguish confirmed findings from assumptions and checks you could not run.
Review only: do not edit, commit, push or merge. If there are no findings, say so
and identify any remaining validation gaps.
```

The builder addresses the review findings and the owner's decisions in the same
PR. A review-only session remains read-only unless the owner changes its task.

## Done checklist

Before opening the pull request:

- [ ] Every acceptance criterion is covered by a meaningful test or, for documentation-only work, an appropriate document check; anything not done is listed in the pull request with the reason.
- [ ] Backend changed: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run lint-imports`, `LISTENUP_REQUIRE_DB=1 uv run pytest`. Require storage with `LISTENUP_REQUIRE_S3=1` for S3 checks; distinguish skips from passes.
- [ ] Migrations (when the schema changed): `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade -1` and back up; a new table with `user_id` has the `own_rows` policy and explicit grants.
- [ ] API changed: `uv run python scripts/export_openapi.py` and `pnpm api:generate`, with the generated files committed; each new route is in `tests/integration/access_registry.py`.
- [ ] Web changed: `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test`, `pnpm build`, `pnpm size`, and `pnpm e2e`.
- [ ] A significant decision has an ADR in `docs/adr/`; a new convention for an area is added to `docs/conventions.md`.
- [ ] Commits follow the rules in `CLAUDE.md`.
- [ ] The PR describes the resulting behavior, relevant checks and outcomes, skipped/unrun checks with reasons, and any owner decisions still needed. Mark unrelated checks not applicable; do not claim unrun checks passed.

Before merge: required CI is green, fresh-session review is complete, findings
are addressed and policy questions are resolved. The owner merges. Model choice
and a passing local check do not replace these gates.

## Avoid

- One long session that coordinates many helpers: each step resends the whole history, and helpers start cold.
- Pull requests that carry several stories: they are slow to review and hide bugs.
- Repeating the full suites while working: CI runs them on every push.
- Assuming Claude hooks, slash commands or GitHub event wakeups exist in Codex. Check CI when handing off or when the owner resumes work; use event-driven follow-up only where it is configured.
