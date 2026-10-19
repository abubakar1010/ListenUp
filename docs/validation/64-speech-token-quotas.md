# Follow-up to #64 / PR #159: speech token quota admission

Branch: `fix/64-speech-token-quotas`, based on merged PR #159 (`a74e930`).
This fixes the review's P2 quota finding and closes its deterministic validation
gaps. No provider, model, prompt, schema migration, HTTP or web behavior is added.

## Behavior and tests

Speech admission reserves calls/audio but cannot bound tokens. The gateway now
rejects any speech-role `tokens` cap before adapter creation, including zero caps,
rather than admitting calls with a zero token reservation. Text token admission
and existing speech call/audio admission are unchanged. ADR 0041 and the AI
conventions record this supported configuration boundary (NFR-AI-8).

| Review item | Named test and observable assertion |
| --- | --- |
| P2: token-metered speech can exceed its allowance | `test_speech_token_quotas_are_rejected_before_adapter_creation`: all three speech roles, all three quota periods, and zero/positive caps raise `AIConfigError`; no adapter is created and no accounting attempt occurs. Existing token-limited text and call/audio-limited speech tests retain their allowed paths. |
| Concurrent duplicate settlement | `test_concurrent_duplicate_settlement_refunds_only_once`: eight independent stores settle one reservation; all three persisted buckets retain exactly one call and 15 tokens, and the ledger records actual usage once. |
| Settlement racing admission | `test_admission_racing_settlement_observes_committed_capacity`: database-lock synchronization forces each order, with bounded waits and no sleeps. Admission before settlement is denied; admission after settlement succeeds. Exact persisted counters and both ledger rows are asserted. |
| Worker death mid-call | `test_worker_killed_mid_call_keeps_durable_reservation`: kill a separate process after its provider announces entry; the reservation stays `pending`, estimated, and charged in all three buckets. A fresh store denies another call. |
| Ineligible fallback after primary retry | `test_ineligible_fallback_is_skipped_after_primary_retries`: transcription and learner-gist text calls retry the eligible primary, skip a training/unknown-policy fallback entirely, and reach the next eligible provider. Exact call order and outcomes are asserted. |

## Actual red/green and assertion quality

From `apps/api`, before changing gateway code:

```sh
uv run pytest tests/unit/ai/test_safeguards.py -q -k speech_token_quotas
```

Observed **18 failed, 62 deselected**, all because the expected configuration
error was absent. After adding the guard, `uv run pytest tests/unit/ai
tests/contract -q` passed **153 tests**. The later concurrency, process-death and
fallback tests characterize the existing safeguards; they are not claimed as
test-first changes to those safeguards. Their focused command:

```sh
LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_ai_accounting.py tests/unit/ai/test_safeguards.py -q -x
```

Observed **105 passed** against PostgreSQL 16. An isolated in-memory mutation
removed only the new quota guard and reran the focused quota selection: **18
failed, 66 deselected**, detecting the defect. It changed no source file. These
observations are recorded development evidence; CI cannot establish chronology.

## Verification

The first required-service full run reported **1 failed, 1266 passed, 1 performance
test deselected**. The existing real-storage transcript test reached an unmigrated
default database through `get_accounting()` and raised `AIUnavailable("accounting
unavailable")`. The throwaway test databases were migrated, but the local default
database had not been prepared as CI's migration step prepares it. After `uv run
alembic upgrade head` and `uv run alembic check` (no drift), the focused transcript
audio file passed **2 tests** without any source change. The complete rerun below
passed after that setup correction; the setup failure is not behavior Red.

Ruff check/format, strict mypy (**142 source files**) and all **six import
contracts** passed. Real-storage smoke tests passed **3 tests**. PostgreSQL 16 and
SeaweedFS run in local Docker containers; PostgreSQL 16.15 client tools were
copied from the database image for the real backup/restore tests.

Final verification after preparing the default database:

- `PATH=/workspace/work/pg16:$PATH LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 uv run pytest -m 'not performance' --cov --cov-report=term-missing:skip-covered --cov-report=xml --cov-report=html`: **1267 passed, 1 performance test deselected**, no skips, 279.67 seconds. This includes the new concurrency/crash assertions, restricted-role, migration, retention, backup/restore and real-storage transcript tests.
- `uv run pytest -m performance --no-cov`: **1 passed**, separately from coverage.
- `uv run python ../../.github/scripts/check-coverage.py api coverage/coverage.xml`: every runtime file resolves. `uv run diff-cover coverage/coverage.xml --compare-branch origin/main --fail-under 90`: **2/2 changed executable lines covered (100%)**. The new guard exercises denial and allowed paths; existing empty-entry/preload/loop and real alignment-engine gaps remain outside this change. No threshold or exclusion changed.
- Final Ruff check/format passed. `uv run alembic downgrade -1`, upgrade to head, and drift check passed on the local default database, in addition to the full suite's migration checks. No migration is added or changed.
- No HTTP/schema/web changes: generated client, access-registry additions and web checks are not applicable. Image builds and vulnerability scans were not run locally; they remain CI checks on the pushed revision. No alert rules or pure spike helpers changed.

## Remaining policy and independent gates

Claude Code is unavailable; this follow-up used Codex. A fresh independent review
of these material fixes remains required. No historical review approval was
invented: the question of where PR #159's pre-merge review was recorded remains
with the owner. ADR 0037's golden-set handoff versus ADR 0041's #66 deferral also
remains an owner clarification; no new model or provider is enabled here and no
model-quality pass is claimed.

Actual deployment-host performance and real-provider/model acceptance retain
their existing gates. No acceptance requirement is waived by these tests.
