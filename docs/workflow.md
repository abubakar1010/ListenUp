# How a story is built

One story, one session, one pull request. The aim is the fewest tokens for work that is right the first time: rework is the most expensive thing a session can do, so quality checks sit where they are cheapest, and every session stays small.

## The steps

1. **Ready (owner).** The issue has acceptance criteria and its dependencies are merged. A story whose blocker is open waits; it is not built around the gap.
2. **Plan (complex stories only).** A story that adds a module, changes the data model, or touches security, privacy or AI grading starts with a plan of 10 to 15 lines: files to change, data changes and migration, risks, and the tests that prove each acceptance criterion. The owner approves or corrects it before any code.
3. **Build.** Tests are written with the code. Run only the tests for the area while working; run the full checks once, before opening the pull request (the checklist below). Open one pull request for the story.
4. **CI.** Every push runs the full suites, the image builds and the vulnerability scan. A red build is fixed in the same pull request.
5. **Review.** A fresh session reviews the pull request (`/code-review <number> medium`). Its findings are fixed in the same pull request.
6. **Merge (owner).** Merge, close the session, and start the next story from `main`.

Run two or three sessions at once on stories that touch different areas. Each has its own branch and pull request, so nothing needs merging by hand.

## Choosing the model

| Story | Plan step | Model |
| --- | --- | --- |
| Contained UI, CRUD endpoints, tests, documentation | No | Sonnet |
| New module or data model change | Yes | Opus to plan, Sonnet to build |
| Security, privacy, AI grading, cross-module | Yes | Opus |
| Review of a pull request | No | Opus |

## Prompt template for a story session

```
Story: #<number> <title>. Read the issue first.
Area: <module and directories>. Do not change: <areas owned by other open work>.
Plan first: <yes or no>. If yes, stop after the plan and wait for approval.
Read docs/conventions.md for the areas you touch. Read the design documents only
where an acceptance criterion needs them.
Done means every item of the checklist in docs/workflow.md, then one pull request.
```

## Done checklist

Before opening the pull request:

- [ ] Every acceptance criterion is covered by a test; anything not done is listed in the pull request with the reason.
- [ ] Backend: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run lint-imports`, `LISTENUP_REQUIRE_DB=1 uv run pytest`.
- [ ] Migrations (when the schema changed): `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade -1` and back up; a new table with `user_id` has the `own_rows` policy and explicit grants.
- [ ] API changed: `uv run python scripts/export_openapi.py` and `pnpm api:generate`, with the generated files committed; each new route is in `tests/integration/access_registry.py`.
- [ ] Web changed: `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test`, `pnpm build`, `pnpm size`, and `pnpm e2e`.
- [ ] A significant decision has an ADR in `docs/adr/`; a new convention for an area is added to `docs/conventions.md`.
- [ ] Commits follow the rules in `CLAUDE.md`.

## Avoid

- One long session that coordinates many helpers: each step resends the whole history, and helpers start cold.
- Pull requests that carry several stories: they are slow to review and hide bugs.
- Repeating the full suites while working: CI runs them on every push.
- Scheduled check-ins on a pull request: GitHub events wake the session when something changes.
