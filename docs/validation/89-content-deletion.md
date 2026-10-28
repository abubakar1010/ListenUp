# Content deletion (#89) validation

Owner-approved scope: last-reference YouTube deletion proves `ref_count = 0`
and leaves shared caches eligible for #93's seven-day sweep. Conversion-only
writer fencing is included; the remainder of #228 stays separate.

## Recorded TDD

Commands below run from the repository root unless otherwise stated, after
sourcing `/workspace/listenup-runtime/activate.sh` for this environment.

| Cycle | Red command and actual outcome | Green command and actual outcome |
| --- | --- | --- |
| Schema/barrier | `LISTENUP_REQUIRE_DB=1 uv run --project apps/api pytest apps/api/tests/integration/test_content_deletion_schema.py -q`: 2 failures (missing deletion column and writer table) | From `apps/api`: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_content_deletion_schema.py tests/integration/test_migrations.py -q`: 6 passed, including downgrade/upgrade, drift and single head |

Implementation and final validation are in progress. No unrun check is claimed.
