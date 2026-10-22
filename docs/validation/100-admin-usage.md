# #100 part 2: administrator usage reports

Scope: usage only; #166 supplies the role and job view. Implements SRS 2.2 and
NFR-AI-10. ADR 0051 documents the separate report connection and quota semantics.
Protected review, marks and AI-layer files are unchanged.

## Acceptance criteria and evidence

| Criterion | Named tests |
| --- | --- |
| Provider/day calls, token units, audio seconds, stored projected cost; last 30 UTC dates | `test_usage_aggregates_30_utc_days_without_double_counting`, `test_usage_empty_report_and_utc_boundary` |
| Day/month free quotas; zero, uncapped, removed provider/unknown allowance | `test_usage_preserves_zero_uncapped_and_unknown_limits`; web `zero allowance and uncapped dimensions do not appear as unused free quota` |
| Ordinary learner and unverified listed account get 404; signed-out caller gets 401 | `test_usage_is_hidden_from_non_admins`, `test_access_cross_learner.py` with the new `Admin()` entry; browser `a learner who opens usage receives the ordinary page-not-found` |
| No learner media/text, raw call records, provider options or error details | Explicit response field/value assertions in the aggregate test; `test_usage_invalid_config_is_unavailable_without_leaking_details`, `test_usage_does_not_fall_back_to_the_api_role`, `test_report_login_has_no_identity_or_accounting_write_access` |
| Separate report login, no privileged fallback; missing configuration is 503 | `test_usage_without_report_connection_is_explicitly_unavailable`, `test_usage_missing_config_is_unavailable`, `test_usage_does_not_fall_back_to_the_api_role` |
| Connection forwarded to the API only | `test_compose_passes_report_connection_only_to_api` |
| Accessible loading, errors, empty data, refresh and navigation | `UsagePage.test.tsx`; browser `an admin navigates to usage by keyboard and reads it at 360 px` |

## Test-first chronology

Backend disclosure: the first intended red run of
`LISTENUP_REQUIRE_DB=1 uv run --frozen pytest -q tests/integration/test_admin_usage.py`
had four setup errors because PostgreSQL was stopped. Implementation advanced
before a valid red result; this is a test-first gap, not claimed as TDD evidence.
After restarting services, the tests were checked against the original route and
then against an isolated export of the full base source at `2800167`:

```sh
PYTHONPATH=/tmp/listenup-usage-baseline/apps/api/src LISTENUP_REQUIRE_DB=1 \
uv run --frozen pytest -q \
tests/integration/test_admin_usage.py::test_usage_aggregates_30_utc_days_without_double_counting \
tests/integration/test_admin_usage.py::test_usage_without_report_connection_is_explicitly_unavailable
```

Both failed as expected on the absent endpoint (404 instead of 200/503). The
implementation passed the initial four tests, then all 23 admin integration tests
after aggregate SQL was moved into the repository. Expanded edge cases were green
characterization/validation of that behavior, not additional claimed red cycles.
Admin plus cross-learner checks passed 30 tests.

Frontend red: `pnpm vitest run src/features/admin/UsagePage.test.tsx` failed because
the planned `UsagePage` interface did not exist (module resolution; zero tests
executed). After implementation, the usage/jobs component run passed 14 tests.
Refresh coverage was added afterwards; the final complete coverage run passed
389 tests in 41 files. Type checking caught optional versus explicit-null quota
limits, corrected in the response schema and regenerated client.

Compose red: `uv run --frozen pytest -q tests/unit/admin/test_report_config.py`
failed because the API environment lacked the report URL. After adding the
API-only override, that test plus existing media configuration checks passed all
four tests. Documentation and generated schema changes have no executable TDD
requirement.

## Security regression quality

Isolated source copies were used, without modifying the working implementation:

- Remove `SET LOCAL ROLE listenup_readonly`: the no-API-fallback test fails with
  200 instead of 503. It detects silently reading reports as the learner API role.
- Disable the admin role gate: both non-admin cases fail with 503 instead of 404.
  Authorization must precede even checking report configuration.

The privacy test seeds task/model/option sentinels and checks they are absent.
Separate-period fixtures detect join multiplication, refused calls, future calls
and duplicate minute/day/month consumption. The role test uses a non-superuser
report login and verifies no identity reads or accounting writes.

## Final validation

- Backend format, lint, strict types and six import contracts passed.
- Frontend lint, format, types, 389 tests with coverage, production build and
  bundle budget passed (124.6 kB initial JavaScript gzip; 200 kB cap).
- Playwright: 39 passed, including keyboard navigation, learner 404 and narrow
  usage layout. These tests mock the API; database integration proves the server.
- Backend full coverage command from `docs/testing.md`, with both
  `LISTENUP_REQUIRE_DB=1` and `LISTENUP_REQUIRE_S3=1`: 1,633 passed, one performance
  test deselected; no skipped or failed tests (404.40 seconds). The new Compose
  test was added after this run's collection and passed separately alongside the
  three existing media configuration tests.
- `uv run --frozen pytest -m performance --no-cov`: one passed, 1,634 deselected.
- Coverage inventory checks passed for both applications. `diff-cover` against
  base `28001678a446d1d05d14c7755aa192898a472168` reports API 97/97 changed
  executable lines covered and web 22/22: 100% in each. The changed admin backend
  repository and usage module also have full line and branch coverage; no changed
  security branches are uncovered. Backend combined line/branch coverage is 97%;
  frontend line coverage is 94.85%, branch coverage 86.7%.
- No migration: existing read-only grants cover both accounting tables.
- Fresh-session independent review and remote CI remain merge prerequisites.

Deployment requires `LISTENUP_ADMIN_REPORT_DATABASE_URL` for a separate login
granted only `listenup_readonly`; missing configuration intentionally yields 503
only for the admin usage endpoint. See ADR 0051 for provisioning and limitations.
