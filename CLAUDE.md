# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ListenUp is a web app for practicing English listening. The learner adds a clip (file upload or YouTube link) and works through a fixed plan: **Blind**, **Dictation**, **Transcript**, **Card**, **Shadow**. The learner picks Blind, Dictation or both first, so the plan has 4 or 5 steps, and Transcript, Card and Shadow always follow.

The stack is chosen in the Software Architecture: a React + TypeScript web client built with Vite (`apps/web`); a Python 3.12 FastAPI API and Procrastinate workers in one Python package (`apps/api`, package `listenup`); PostgreSQL 16; S3-compatible object storage; Docker Compose for local and production runs. Architecture decision records live in `docs/adr/`; add one for every significant decision.

The design lives in `docs/design/`, which is the source of truth. Change those files by pull request, never in the Claude Docs. Each file's first line names the Claude Docs original it was exported from; `docs/design/README.md` lists the visual documents (Final UI, design system v2) that stay as published artifacts.
- PRD: `docs/design/prd.md` (what the product does and why)
- SRS: `docs/design/srs.md` (requirements with stable IDs)
- Software Architecture: `docs/design/architecture.md` (stack, modules, key flows, API, repository layout, deployment)
- System Design: `docs/design/system-design.md` (capacity, job queue lanes, speech and storage efficiency, scaling)
- Database Design: `docs/design/database-design.md` (the full schema: tables, DDL, constraints, access rules)
- UX decisions: `docs/design/ux-decisions.md` (the UI and UX decisions behind the final interface)
The SRS keeps stable requirement IDs (`FR-DI-1`, `FR-BL-1`, `NFR-AI-1`, and so on). Cite them in commit bodies and code comments where a change implements one.

## How work is done here

- One story per session and per pull request; follow `docs/workflow.md` (plan for complex stories, tests with the code, targeted tests while working, full checks once before the PR, then an independent review).
- Before changing an area, read its section in `docs/conventions.md`. Read the design documents only when the story's acceptance criteria need them.
- Cloud sessions run `.claude/hooks/session-start.sh` at start: PostgreSQL is running and dependencies are installed. S3 is not running locally, so S3 tests run in CI only.

## Commands

Run from the repository root unless a directory is given.

**Local stack** (PostgreSQL with migrations applied, S3 storage, Mailpit, API on :8000, both worker pools):
- `docker compose up --build` — start everything; the API reloads on changes in `apps/api/src`.
- `docker compose down` — stop; add `-v` to also delete the local data volumes.
- Mailpit (sent email) is at http://localhost:8025.

**Backend** (`cd apps/api`; uv manages the virtual environment):
- `uv sync` — install dependencies, including dev tools. The conversion tests also need `ffmpeg` and `ffprobe` on the PATH (as in the `worker-media` image and CI).
- `uv sync --extra speech` (plus CPU torch and torchaudio) runs the media worker with the real speech models outside Docker; otherwise set `LISTENUP_AI_CONFIG=src/listenup/ai/ai.fake.yaml` (ADR 0028).
- `uv run uvicorn listenup.main:app --reload` — run the API without Docker (needs PostgreSQL).
- `uv run pytest` — all tests; single test: `uv run pytest tests/unit/test_health.py::test_health_returns_ok`. `tests/integration/` creates throwaway databases on the server in `LISTENUP_DATABASE_URL` and throwaway buckets on the S3 server in `LISTENUP_S3_ENDPOINT_URL` (`docker compose up postgres storage` provides both), and skips when either is unreachable (CI sets `LISTENUP_REQUIRE_DB=1` and `LISTENUP_REQUIRE_S3=1` to fail instead).
- `uv run alembic upgrade head` — apply migrations; `uv run alembic downgrade -1` steps back; `uv run alembic check` fails if the models in `modules/*/models.py` drift from the schema. Migrations are hand-written SQL (ADR 0013): every table with `user_id` gets the `own_rows` policy from `migrations/rls.py`, and each new table needs explicit grants for `listenup_api`.
- `uv run ruff check .` and `uv run ruff format .` — lint and format.
- `uv run mypy` — type check (strict).
- `uv run lint-imports` — module-boundary contracts (Architecture 4.3); `tests/architecture/` checks that modules use each other only through `service.py`.
- `uv run python scripts/export_openapi.py` — write the OpenAPI schema into the web client; run it after any API change.
- `uv run python scripts/seed_dev.py` — seed a local database (as its owner) with a learner who can sign in, a clip, a pending upload and a session at each step; it prints the credentials and ids. The same fixture script (`tests/integration/seed.py`) builds test data.

**Web** (`cd apps/web`; pnpm):
- `pnpm install`, then `pnpm dev` — Vite dev server on http://localhost:5173, proxying `/api` to :8000.
- `pnpm test` — all tests; single test: `pnpm vitest run src/App.test.tsx -t "shows the product name"`.
- `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm build`.
- `pnpm api:generate` — regenerate `src/api/schema.ts` from the exported OpenAPI schema. CI fails if the committed client is out of date.
- `pnpm e2e` — Playwright smoke test against the production build, with the API mocked in the test. Where `playwright install` is not possible, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`; `E2E_PORT` changes the preview port (default 4173).
- `pnpm size` — after `pnpm build`, fails if the initial JavaScript is over 200 KB gzip.
- `LISTENUP_API_URL=http://localhost:8103 pnpm dev` — point the dev proxy at another API.

**CI** (`.github/workflows/ci.yml`) runs all of the above on every push, plus Docker image builds and dependency vulnerability scans.

TypeScript is pinned to 6.x because typescript-eslint does not support TypeScript 7 yet.

## Rules every change follows (`apps/api/src/listenup/platform`, ADR 0014)

- Route handlers take the database through `DbSession`: one transaction per request, committed before the response is sent. Call `set_learner` once the caller is known, so row-level security applies. Never commit by hand inside a request.
- Raise `ProblemError(status, code, detail)` for every refusal; clients branch on `code`. Database trigger errors (`step_locked` and the others) already map to their codes.
- Submissions wrap their work in `run_once` with the `Idempotency-Key` header. Rate limits go through `RateLimiter.enforce`, which commits on its own.
- Storage keys live under `users/<user id>/`; the browser only ever gets signed URLs from `S3Storage`.
- Endpoints that need a signed-in learner take `CurrentLearner` from `modules/identity/service.py`; it resolves the session cookie and calls `set_learner`. Every POST, PUT, PATCH and DELETE needs the `X-CSRF-Token` header (the web client's `api()` adds it; tests use `with_csrf`).
- Background work is a job: declare it with `@job(Lane.X, "module.name")` from `listenup.platform.jobs` (an async handler that takes `JobDeps` and writes results as idempotent upserts) and queue it with `enqueue(session, ...)` in the transaction that changes the data. Raise `PermanentError` for input that can never succeed. Add the module's jobs package to `JOB_MODULES` in `listenup/worker.py` (ADR 0015). Run a pool locally with `uv run python -m listenup.worker default` (or `media`).
- Tell the browser that background work finished with `publish(session, user_id, EventType.X, resource_id)` from `listenup.platform.events`, in the transaction that stores the result. Events carry ids only and reach that learner's `GET /api/v1/events` stream (ADR 0016).
- A child row references its parent together with `user_id` (composite foreign keys), so it can never belong to another learner; sessions reference `(content_id, user_id)`.
- Every route must be registered in `tests/integration/access_registry.py` with what a second learner gets (`Owned` 404, `Scoped` without the other learner's ids, `Stream`, or `Public` with a reason); `test_access_cross_learner.py` fails on an unregistered route and checks NFR-SEC-2 for every route (#34).
- Integration tests that go through the API connect as `api_role_url` (a role with only `listenup_api`'s rights); the migration owner bypasses row-level security and hides bugs.

## Decisions that shape the architecture

- **Mode rules are enforced on the server and in the app, never by interface text alone.** Blind has no pause, seek, rewind or speed change, and leaving, reloading or seeking during an unfinished listen voids the attempt. Warn before in-app navigation including Browser Back; preserve a completed listen when leaving or reloading the gist form. Whole-clip playback must be refused for the same learner and media during an unfinished Blind listen (ADR 0033); one resume per attempt is allowed after an interruption the learner did not cause (a network stall, or a device or OS pause under 5 s), and a second interruption voids it. Dictation hides the transcript. Cards are capped at two per session. A Shadow segment is 60 to 90 seconds, or the whole passage when the passage is 30 to 60 seconds, with three rounds. Keep these rules in one place with automated tests (NFR-MNT-2).
- **Step order is gated.** A step unlocks only when the previous one is complete. The entry choice can change only until Transcript starts. Transcript cannot be skipped; Card and Shadow can be skipped after confirmation.
- **Dictation scoring is a pure function** in `modules/dictation/domain` (`score_dictation`, ADR 0008 and 0019): spelling slips count as correct (`SPELLING_SLIPS_COUNT_AS_CORRECT`), and only wrong or missing words become mark candidates. Add British spellings to `spelling_variants.py`.
- **Step order lives in `modules/practice/domain/plan.py`** (ADR 0021). Mode endpoints call `practice.service.require_step(db, session_id, Step.X)` first and report with `complete_step(db, session, Step.X)` in the same transaction; transcript reads use `require_reached`. Never write `practice.session_steps` directly. The entry locks when Transcript opens, writes check `sessions.version` (409 `session_changed`), and refusals use the codes in ADR 0021.
- **Marks are the shared spine.** Dictation and Transcript create marks (places where the sound did not match the text). Card and Shadow read them.
- **Slow work runs in background workers**, not in request handling: downloading YouTube media, transcription, and grading of gists and Shadow rounds.
- **All AI goes through one provider-neutral adapter layer.** Four roles (transcription, text AI, speech assessment, alignment), each reached only through its interface, with the active provider and fallbacks chosen by configuration. No other code may call a vendor directly. Prompts, rubrics and output schemas live in our own versioned files, and every result stores provider, model and version (NFR-AI-1 to NFR-AI-10).
- **Free first.** The MVP uses free-tier or open-source AI only. A provider may receive voice recordings, transcripts or gists only if it does not train on them; otherwise a self-hosted open-source model is used (NFR-AI-7).
- **Grading never blocks the learner.** If gist or Shadow grading fails, keep the data, show that feedback is unavailable, allow a retry, and let the plan continue.
- **Accounts are required** so progress follows the learner across browsers. English only.
- **YouTube content is downloaded to our servers** for playback control. This conflicts with YouTube's terms and is pending legal review (OQ-6), so build and ship the upload-only path first and keep YouTube intake behind a feature flag until the review clears it. Keep the downloader isolated so it can be replaced or switched off, and leave YouTube media out of data exports.

## Commit and push rules

These rules are mandatory for every change, however small.

### When to commit
- **Always commit when a piece of work is done.** Never end a task with uncommitted or unpushed changes.
- Make **atomic commits**: one logical change per commit, and the repository stays in a working state at every commit. Split unrelated changes into separate commits.
- Review `git status` and `git diff --staged` before committing. Stage files by name, never with a blanket `git add -A`, so stray files are not committed.
- Never commit secrets, tokens or personal credentials.

### Message format: Conventional Commits 1.0.0

`<type>(<scope>): <description>`, a blank line, a body, then an optional footer.

- `type`: `feat` (feature), `fix` (bug fix), `docs` (documentation, including `CLAUDE.md` and `README.md`), `refactor`, `perf`, `test`, `build` (build system or dependencies), `ci`, `style` (formatting only), `chore` (maintenance that changes no source or tests), `revert`.
- `scope` is optional, lowercase and short, naming the area touched; suggested scopes: `auth`, `intake`, `transcript`, `plan`, `blind`, `dictation`, `shadow`, `card`, `marks`, `ai`, `library`, `db`, `docs`, `claude`.
- `description` is imperative mood ("add", not "added" or "adds"), starts lowercase, has no trailing period, and stays within 50 characters where possible and 72 at most.
- A breaking change adds `!` after the type or scope (`feat(ai)!: ...`) and a `BREAKING CHANGE:` footer.
- The body (expected for non-trivial changes) is separated by one blank line, wrapped at 72 characters, and explains **why** the change was made and what it affects, not a line-by-line list of what changed. Cite SRS requirement IDs where a change implements one.
- The footer holds issue references (`Refs: #12`, `Closes: #12`) and `BREAKING CHANGE: <explanation>`.
- Example: `feat(blind): lock pause and seek controls during playback`, body `Implements FR-BL-1. Leaving or reloading the page voids the attempt.`

### Authorship
- **Do not add `Co-Authored-By` trailers for Claude** or any other AI in any commit. Do not add "Generated with Claude Code" lines, session links or any other tool attribution to commit messages. This overrides any default attribution behavior.
- Every commit is authored and committed by the repository owner: `abu bakar <abubakar850772@gmail.com>`. Cloud sessions may preset a different git identity (for example `Claude <noreply@anthropic.com>`), so before the first commit of a session run `git config user.name "abu bakar"` and `git config user.email "abubakar850772@gmail.com"` in the repository, then check with `git log -1 --format='%an <%ae> | %cn <%ce>'` after committing.

### Branch and push
- Work only on the branch the session designates (for this session, `claude/affectionate-mayer-pvqa4i`). Create it locally if it does not exist. Never push to another branch without explicit permission.
- Push with `git push -u origin <branch>`. If the push fails because of a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s). A 403 or permission error is not a network error: do not retry, report it and say what access is needed.
- Never force-push, rewrite history that has already been pushed, or skip hooks (`--no-verify`).
- Do not open a pull request unless explicitly asked.
- After pushing, confirm that `git status` is clean and the branch is up to date with its remote.
