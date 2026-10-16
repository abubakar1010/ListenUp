# Story #32: Google sign-in validation

Base: current `main` at `f2220fbb85033e24b21612e31729299bdb799d04`.
Branch: `feat/32-google-sign-in`, validated with
`.github/scripts/check-branch-name.sh "$(git branch --show-current)"`.
Dependency #29 is in merged PR #126, merge commit
`035d6ea4158ee8bdbe857cd033a06a44d5d03374`, verified as an ancestor.
The issue itself was still open; merge evidence, rather than issue state, was used.
The owner approved the 15-line plan and its linking/lockout policies before code.

## Acceptance criteria and test evidence

Backend commands below run from `apps/api`; web commands run from `apps/web`.
Provider responses are mocked at HTTP token/JWKS boundaries with RSA-signed test
ID tokens. No automated test calls live Google.

| Requirement | Named tests / observable assertions |
| --- | --- |
| FR-ACC-1: create or link and sign in | `test_google_creates_verified_passwordless_account_and_reuses_subject`; `test_verified_google_email_links_unverified_password_account_despite_password_lock`; same user ID, verified email, no password for a new Google account, stable subject despite email changes |
| FR-ACC-2 and account races | `test_concurrent_callbacks_create_one_identity`; advisory-locked transactions resolve to the same account; existing password/two-browser tests remain green |
| State, nonce and token validation | `test_state_browser_binding_cancellation_and_replay`; `test_invalid_tokens_are_refused_without_creating_account`; invalid nonce, issuer, audience, expiry, future issue time, authorized party, unverified email, empty subject, malformed token and invalid signature cause no account/session; provider token/JWKS failures also refuse |
| Expiration / redirects | `test_expired_state_and_reauth_proof_are_refused`; `test_untrusted_redirects_fall_back_to_library`; `test_local_destination_is_preserved` |
| Explicit restore / DR-1 / ADR 0033 | `test_google_restore_is_explicit_single_use_and_deadline_checked`; Keep leaves deletion pending, Restore starts a session, a consumed continuation cannot replay, deadline expiry refuses; original destination survives |
| Cross-tab Keep it deleted | `test_keep_deleted_also_signs_out_a_session_created_in_another_tab` |
| FR-ACC-4: Google-only deletion | `test_google_only_deletion_requires_fresh_matching_identity_and_explicit_confirmation`; wrong subject and stale auth_time refuse, Google return alone does not delete, confirm=false refuses, final confirm disables the account |
| Deletion session binding | `test_google_reauth_is_bound_to_the_original_login_session`; changing session before callback/proof use refuses; a stale Google cookie cannot block a current password |
| Export / purge / isolation | `test_google_identity_export_and_cascade`; `test_google_identities_are_scoped_by_the_restricted_api_role`; `test_the_purge_removes_everything_after_the_grace_period` now seeds a Google identity and flow; export includes identity and safe metadata, omits secrets/payload, purge removes rows, API role cannot read/attach another learner's identity |
| Throttling / secrets | `test_google_start_has_ip_rate_limit`; `test_oidc_callback_secrets_never_reach_logs`; missing credentials produce `google_unavailable` |
| Accessible controls / web outcomes | `AuthForm.test.tsx` covers both Google links, cancellation, explicit restore/decline, expired continuation and terminal refusal without a trapped dialog; `DeleteAccountSection.test.tsx` covers Google confirmation and checkbox/final-action requirements |
| Browser navigation | `e2e/google.spec.ts`: keyboard focus and Enter navigate through the Google control and a full page load into the new account; API/provider navigation is mocked, not a live-stack claim |

## Actual red / green chronology

Red logs were recorded during the cycles; infrastructure failures were not counted
as proof of missing behavior. Green commands were also run after cleanup.

| Cycle | Red command and observed result | Green / refactor command and observed result |
| --- | --- | --- |
| Start / configuration | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_oidc.py -q`: 2 failed (routes returned 404) | Same command: 2 passed |
| Callback / linking / invalid provider results | Same focused file after adding callback tests: 10 failed, 2 passed (callback missing) | Same command: 12 passed |
| Restore / Google deletion / expiry | Same focused file after adding lifecycle cases: 3 failed, 12 passed | Same command: 15 passed |
| Export | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_data.py -q`: corrected fixture and withdrawn contribution produced `KeyError: identity.oauth_accounts` | Same command after reapplying contribution; later restricted-role/purge group: 3 passed |
| Google UI / restore question | `pnpm vitest run src/auth/AuthForm.test.tsx`: 3 failed, 7 passed (Google links/question absent) | Auth and deletion files together: 19 passed; additional characterization and refusal cases later: 23 passed |
| Google deletion UI | `pnpm vitest run src/features/account/DeleteAccountSection.test.tsx`: 2 failed, 7 passed (Google confirmation/control absent) | Both focused web files: 19 passed |
| Logging / rate limit | `uv run pytest tests/unit/test_log.py::test_oidc_callback_secrets_never_reach_logs tests/integration/test_google_oidc.py::test_google_start_has_ip_rate_limit -q`: both failed | OIDC/data/log group after implementation: 34 passed |
| Destination retained by restore | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_oidc.py::test_google_restore_is_explicit_single_use_and_deadline_checked -q`: failed on missing `next_path` | Full focused OIDC/data group: 21 passed |
| Password fallback | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_oidc.py::test_google_reauth_is_bound_to_the_original_login_session -q`: failed, stale Google proof blocked valid password deletion | Focused OIDC/data group: 21 passed |
| Cross-tab decline | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_oidc.py::test_keep_deleted_also_signs_out_a_session_created_in_another_tab -q`: failed, replacement session still reached `/me` | Same command: 1 passed |
| Restore refusal usability | `pnpm vitest run src/auth/AuthForm.test.tsx -t 'restore refusal closes'`: failed, dialog stayed open | Both focused web files: 23 passed |
| Malformed redirect | `uv run pytest tests/unit/test_google_redirects.py -q`: 1 failed, 5 passed (`http://[` raised ValueError) | Same command: 6 passed |
| Expired deletion proof retry | `pnpm vitest run src/features/account/DeleteAccountSection.test.tsx -t 'expired Google deletion proof'`: failed, the page had no Google retry link | Both focused web files: 24 passed; final web suite: 310 passed |
| Coverage instrumentation | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_google_oidc.py tests/unit/test_google_redirects.py -q --cov=listenup.modules.identity.google_api --cov=listenup.modules.identity.oidc --cov-report=term-missing --cov-fail-under=90`: tests passed but gate failed at 84.26%; post-await lines were missed | Same command with supported thread/greenlet tracing configured: 32 passed, 97.97% measured coverage; no threshold or exclusion change |

The first export test run failed in its fixture because it passed a connection
string where a URL was required. That was **not valid Red**. The export
contribution was briefly added following that invalid run: this was a test-first
lapse. It was withdrawn, the fixture corrected, the missing-contribution failure
observed, and the contribution reapplied. An additional isolated source snapshot
under `work/32-pre-export/api` (current source with only the export contribution
removed) was run with `PYTHONPATH="$PWD/src" /workspace/ListenUp/apps/api/.venv/bin/python -m pytest tests/integration/test_google_data.py::test_google_identity_export_and_cascade -q`.
It failed specifically with `KeyError: identity.oauth_accounts`, while the final
source passes. This snapshot did not edit the working source or create a worktree.
The corrected regression therefore
proves the pre-contribution behavior, without claiming the first run was valid.

Subsequent signature/provider/concurrency/isolation cases and the browser test are
additional characterization and regression evidence for implemented behavior;
they are not presented as new test-first cycles. Formatting, OpenAPI metadata and
generated client output need regeneration/format checks rather than artificial Red.

Security assertions expose plausible defects: removing nonce/signature checks
would allow the invalid-token tests to create an account; replaying a consumed
state would return a session instead of 400; accepting a different Google subject
or rotated session would permit deletion; ignoring restore/deadline checks would
unlock `/me` or change the account status in the boundary tests. These checks
assert refusals and absence of unauthorized account/session side effects.

## Final checks

- Final backend: `PATH="/workspace/ListenUp/work/pgclient/bin:$PATH" LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`: **1,122 passed**, one performance test deselected; no skips/errors. PostgreSQL and SeaweedFS were healthy. Coverage reported 96% combined; no repository-wide floor is inferred.
- `uv run pytest -m performance --no-cov`: **1 passed**. This ran without instrumentation.
- Backend `uv run ruff format --check . ../../.github/scripts/check-coverage.py`, `uv run ruff check . ../../.github/scripts/check-coverage.py`, `uv run mypy`, and `uv run lint-imports`: passed; 137 application files type checked, all six import contracts kept. Coverage-script/type regression checks also passed.
- `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade -1`, `uv run alembic upgrade head`: passed. `uv run alembic heads` reports only `32_google_oidc`; the final schema check reports no new operations.
- `uv run python scripts/export_openapi.py` and `pnpm api:generate`: generated files refreshed; redirect statuses and restore's 204 outcome are documented. All four new routes are in the access registry; restricted-role/cross-learner tests passed.
- Web `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test:coverage`: passed, **310 tests across 32 files**; reported web line coverage 94.03%, branch coverage 84.93%.
- `pnpm build` and `pnpm size`: passed; initial JavaScript **120.7 KB gzip** against the 200 KB budget.
- `pnpm e2e`: **31 passed**, using Chromium against the production build with API responses mocked. The new navigation test initially assumed the transient Library heading instead of the stable empty-library page. The assertion was corrected to the real empty state and strengthened to verify the signed-in account's email; no retry or timeout increase was used to hide the failure.
- Coverage completeness: from each app, the workflow's `.github/scripts/check-coverage.py` resolves every runtime source file. `diff-cover ... --compare-branch origin/main --fail-under 90` reports backend **223/225 changed executable lines (99.11%)** and web **30/30 (100%)**. New markup interactions also have role/name tests even when V8 maps their JSX to an existing executable return line.
- The two uncovered backend changed lines are defensive paths in `google_api.py`: propagating an unexpected non-pending `ProblemError` from sign-in and refusing a pending-info query for an account already reactivated elsewhere. Signature, nonce, subject/session mismatch, expiry, replay and explicit restoration decisions have direct allowed/denied assertions. No ignores, exclusions or coverage thresholds were weakened.
- Dependency audits matching CI (`uv export --frozen --no-dev --no-hashes --no-emit-project`, `uvx pip-audit -r ...`, and `pnpm audit --audit-level=high`): no known vulnerabilities.
- `docker compose config --quiet`, branch-name validation and `git diff --check`: passed. Current main was fetched again and incorporated before finalization; it remained `f2220fb`.

The first complete backend attempt reported 1,107 passes and seven setup errors
because pg_dump/pg_restore were missing. Those errors were not passes. Matching
PostgreSQL 16.15 binaries/libraries were made available in the task's scratch
`work/pgclient/bin` using the running PostgreSQL image (no application change).
All seven backup/restore checks then passed, followed by the clean complete run
above. Coverage's original default tracing also missed post-await SQLAlchemy
security decisions; enabling its supported thread/greenlet tracing corrected
measurement without changing application behavior, assertions or exclusions.

Image builds and the complete GitHub CI matrix run on the pushed PR; their remote
status and independent review must still be checked before the owner merges.

## Unverified live checks

No Google client credentials were supplied. Configure
`LISTENUP_GOOGLE_CLIENT_ID`, `LISTENUP_GOOGLE_CLIENT_SECRET` and the exact
registered `LISTENUP_GOOGLE_REDIRECT_URI` before live testing. Google consent,
real authorization-code exchange, provider account selection/fresh-auth behavior,
production HTTPS cookies and deployed callback routing remain unverified.
Automated tests use fixed provider endpoints and mocked responses, not live Google.

Fresh-session independent review and required CI remain owner merge gates. This
session does not merge the PR. ADR 0039 records the approved linking and lockout
policies; #45 transcription and #64 AI gateway code are outside this change.
