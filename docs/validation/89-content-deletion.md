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

## Acceptance criteria and regression assertions

| Requirement | Named tests and what they prove |
| --- | --- |
| AT-9 content half; FR-CI-7; DR-2 | `test_delete_upload_removes_all_derived_rows_and_objects` seeds sessions/steps, attempts/Blind/Dictation data, marks, cards/reviews/audio, Shadow segments/rounds/recordings, corrections, profile subscriptions, gist grades, transcripts, reference profiles, key points and delay rows. It inventories every current learner-owned content/practice/grading table, asserts populated derived fixtures before deletion, checks the remaining rows, verifies the upload media/cache rows and private objects disappear, and retains the unrelated pending upload and analytics. |
| NFR-SEC-2 | The same test compares every inventoried table for learner B and retains B's objects. `test_delete_content_is_confirmed_owned_and_transactionally_queued`, the access registry's new Owned DELETE entry, `test_access_cross_learner.py`, and `test_media_writer_policy_hides_another_learners_rows` exercise restricted API-role denial and side-effect isolation. |
| DR-2 shared media | `test_shared_transcript_and_orphan_eligibility[False]` verifies B's sessions, mark, correction, shared transcript words, profile and key points survive A's deletion; A's sessions/correction/recording disappear and the reference count becomes one. `[True]` deletes B's final reference, verifies zero references and keeps the shared object/cache eligible for #93. |
| Storage first; retry after partial failure | `test_retry_after_partial_storage_failure_keeps_rows_and_manifest` deletes objects before simulating a lost storage response, proves rows and manifest remain, then retries successfully. `test_request_manifest_survives_rows_removed_before_worker` covers a conversion duplicate-merge crash after its row deletion. `test_completed_manifest_recovers_late_browser_upload` proves retained manifests still remove later objects. |
| Durable writer barrier | Schema RESTRICT/RLS tests; `test_conversion_writer_blocks_cleanup_and_retains_uncertain_upload`; `test_conversion_cannot_register_after_content_deletion`; `test_peaks_upload_failure_retains_its_writer`; `test_disabled_account_cannot_start_conversion_write`; `test_account_disabled_after_registration_cannot_reach_conversion_put`; `test_card_writer_defers_content_cleanup_before_any_storage_delete`. These assert that the first storage sweep cannot run while an admitted or uncertain writer remains. |
| Cancellation | `test_cancellation_drains_put_before_releasing_conversion_writer` covers ordinary parent cancellation. `test_direct_put_task_cancellation_preserves_uncertain_writer` models direct child cancellation during shutdown and requires a retained registration, rather than assuming the underlying remote PUT has stopped. |
| Job recovery and ordering | `test_exhausted_deletion_is_reported_and_recovered`; `test_scheduler_recovers_failed_cleanup_without_duplicate_jobs`; `test_missing_deletion_request_is_harmless`; `test_delete_request_does_not_invert_session_content_lock_order`. |
| Real S3 boundary | `test_content_cleanup_removes_real_objects_and_can_run_again` removes playback, original upload, snippet and recording objects in a throwaway real S3 bucket, repeats cleanup, and preserves an unrelated learner's object. |
| Web confirmation/accessibility | Three deletion interaction tests in `LibraryPage.test.tsx`; `content-deletion.spec.ts` covers safe initial focus, Tab/Shift+Tab trapping, Escape and focus restoration, no request on cancel, disabled controls while pending, failure/retry, request body and successful removal. Three accessibility states cover confirmation, pending and error at desktop/360px/dark settings. Browser API responses are mocked; server persistence is proven separately above. |

## Additional actual red/green cycles

Commands here use the repository root and the activated environment unless a
working directory is stated. Logs are scratch evidence under `work/`, not shipped
learner data or committed artifacts.

| Cycle | Actual Red | Actual Green |
| --- | --- | --- |
| Confirmed owned endpoint | `LISTENUP_REQUIRE_DB=1 uv run --project apps/api pytest apps/api/tests/integration/test_content_deletion.py -q` initially failed with HTTP 405 for the missing DELETE route. Upload-removal and partial-failure examples were also written before their implementation. | Focused deletion/conversion run: 38 passed before later supplemental cases. |
| Conversion registration | Same file with `-k 'conversion_'`: 2 failures for the deliberately missing `content.writes` boundary. | Registration, refusal and conversion-neighbor tests passed in the focused run above. |
| Request-time manifest | Same file with `-k request_manifest`: 1 failed because the original upload object survived when rows disappeared first. | Deletion plus export neighbor run: 10 passed after saving the manifest in the API transaction. |
| Lock ordering | Same file with `-k lock_order`: 1 failed (request waited on the held child session). | The same test passed once request snapshots stopped taking child locks. |
| Exhaustion audit | Same file with `-k 'exhausted or lock_order'`: 1 failed (request remained pending), 1 passed. | Exhausted requests now become failed and their successful retry completes; included in the 38-pass run. |
| Disabled account writer | Same file with `-k disabled_account`: 1 failed because registration admitted the disabled account. | The focused 38-pass run includes the refusal. |
| Uncertain peaks PUT | Same file with `-k peaks_upload`: 1 failed for the deliberately missing `writes.store` interface. | Both kinds of PUT now preserve uncertainty; included in the focused 38-pass run. |
| Export inventory | From `apps/api`: `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_export.py::test_export_holds_every_learner_table_and_only_the_learners_data -q`: 1 failed (new writer table absent from export). | Same test plus deletion cases: 10 passed; internal writer id/owner are omitted. |
| Web | From `apps/web`: `pnpm vitest run src/features/library/LibraryPage.test.tsx -t 'delet'`: 3 failed (delete controls absent). | `pnpm vitest run src/features/library/LibraryPage.test.tsx`: 9 passed. |
| Direct child cancellation | Same backend file with `-k direct_put_task`: 1 failed (`DID NOT RAISE Reschedule`, because the registration had been released). | Same file with `-k 'cancellation or direct_put_task'`: 2 passed after retaining uncertainty on direct task cancellation. |

### TDD and process deviations

The expanded shared-transcript fixtures initially failed on invalid fixture data,
which is not Red evidence. They were corrected and strengthened after the job
implementation. Late-upload scheduling and supplemental guard/real-S3 cases were
also added after their implementation; they are not claimed as test-first work.
Following `docs/testing.md`'s disclosure rule, an isolated `git archive origin/main`
scratch checkout ran the final shared/late-manifest/scheduler/card-guard examples:
`PYTHONPATH="$PWD/src:$PWD" LISTENUP_REQUIRE_DB=1 /workspace/ListenUp/apps/api/.venv/bin/python -m pytest tests/integration/test_content_deletion.py -k 'shared_transcript or completed_manifest or scheduler_recovers or card_writer_defers' -q`.
All five failed against the old behavior, with the missing DELETE/job boundary;
the corresponding implementation tests pass. This verifies regression detection
and does not retroactively establish test-first chronology. The fresh reviewer
must assess these deviations.

The early integration merge `4ca90d5` used Git's default merge title rather than a
Conventional Commit title. Its author/committer are the required owner identity;
already-pushed history is retained under the no-rewrite rule. Feature commits use
Conventional Commits and contain no tool attribution.

## Verified so far

- PostgreSQL 16 and S3 were started and checked; backend dependencies and ffmpeg/ffprobe are available.
- Migration CLI upgrade, schema check, downgrade one, upgrade and single-head checks passed.
- Backend format, lint, strict types and all six import contracts passed.
- Real-S3/schema/core selection: 19 passed before supplemental cases.
- Full frontend coverage suite: 731 passed in 67 files; lines 96.53%, branches 89.28% repository-wide.
- Frontend runtime inventory gate passed; changed executable lines: 17/17, 100%.
- Web lint, formatting, types, build and bundle gate passed (126.6 kB initial gzip, 200 kB budget).
- Targeted Playwright deletion test passed; the complete browser/accessibility run is in progress.
- Full backend coverage and uninstrumented performance checks remain to be finalized.

## Deliberate boundaries

No #90 session-deletion feature, #93 retention/orphan sweep, export-writer fence,
or other #228 hardening was implemented. #89's orphan criterion is the explicit
owner-approved eligibility split. Completed manifests require continued scheduled
reconciliation for late signed browser writes, as documented in the runbook.
Unknown conversion/card writes require operator reconciliation; they are never
expired by age. Fresh-session independent review and required CI remain merge gates.

## Final-review additions

- `test_deletion_scrubs_related_replay_text_without_changing_other_requests` was
  observed failing against retained response text before implementation:
  `LISTENUP_REQUIRE_DB=1 uv run --project apps/api pytest apps/api/tests/integration/test_content_deletion.py -k replay_text -q`.
  It passed after scoped cleanup was added. The same-learner unrelated response
  contains a deleted UUID as ordinary submitted text and survives, proving the
  selector uses structured references. A second learner's response also survives.
- The first full backend run recorded 2,534 passed, one opt-in real-profile skip,
  one performance deselection and one failure: `test_scheduled_jobs_run_only_in_the_pool_of_their_lane`
  still expected four schedules. Its exact expected set now includes the fifth
  background schedule, retaining the no-media-lane and no-duplicates assertions.
- The final story/schema/real-storage/worker selection passed all 28 tests after
  that inventory correction and the replay/shutdown fixes. The full backend run
  was restarted on these final production sources.
- The complete Playwright run passed 260 tests with two intentional skips for the
  narrow-only plan-sheet state in desktop/dark projects. All new deletion states
  passed at every applicable width/theme. No browser test establishes live API
  persistence; that is covered by the separate API/database/S3 tests.

## Final verification against main 67d1e76

Main's #87 Shadow completion changes were merged as `b951fa6`. The OpenAPI JSON
and TypeScript client were regenerated from the merged code and matched exactly.
The interrupted environment run is not counted as passing evidence.

- Full required-service backend command: 2,548 passed, one opt-in real-profile
  fixture skipped, one performance test deselected. No PostgreSQL/S3 tests skipped.
- Separate `uv run pytest -m performance --no-cov`: one passed.
- Final export review found internal manifest fields in exported audit reports.
  `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_content_deletion.py -k export_redacts -q`
  failed on the exposed `keys` field before the fix, then passed after a count-only
  export projection. Canceled audit rows with NULL reports remain supported.
- After that final fix, the full export suite plus deletion/schema/real-S3 suites
  ran with `--cov --cov-append`: 48 passed. The allowlisted report counts survive;
  internal keys, prefixes and resource-affinity lists do not reach the export.
- Backend runtime-file inventory passed. Changed-line coverage: 257/258 executable
  lines, 99.6% (diff-cover displays 99%). The sole uncovered line is the defensive
  return when an audit request is removed out of band during storage cleanup;
  ordinary account/content deletion retains these manifests.
- Frontend lint, formatting, types and build passed after the merge. Coverage:
  737 passed in 68 files; changed lines 17/17, 100%. Runtime-file inventory passed.
  Initial gzip JavaScript: 126.7 kB against the 200 kB budget.
- Full Playwright after the merge: 260 passed, two intentional narrow-only state
  skips in desktop/dark projects. All new deletion states were scanned.
- Backend formatting, lint, strict mypy and all six import contracts passed.
  Migration upgrade/check/downgrade/upgrade passed; the final head is only
  `89_content_deletion`.

The real-profile skip requires `LISTENUP_REAL_PROFILE_FIXTURE`; this story changes
no speech model or provider behavior. The #93 sweep remains outside scope under
owner approval. Independent fresh-session review and required CI remain pending
merge gates. All TDD/process deviations above remain explicitly disclosed.

## Independent-review remediation

The independent review found that removing a card after the request snapshot
bypassed the snippet-writer barrier: cleanup completed and cleared the tombstone
while an uncertain writer remained registered. Cleanup now checks both live cards
and the durable manifest's card ids, including on later reconciliation, and
rechecks registrations before clearing tombstones and committing completion.

- Red: `LISTENUP_REQUIRE_DB=1 uv run --project apps/api pytest apps/api/tests/integration/test_content_deletion.py -k card_writer_defers -q`
  produced one pass and one failure: the deleted-card case did not raise
  `Reschedule`. This was observed before the production fix.
- Green: the same command passed both cases. Supplemental assertions verify
  playback/snippet objects and the deleted card's tombstone remain while blocked,
  the audit stays pending, and cleanup completes and removes objects/tombstones
  after explicit writer reconciliation; both cases passed again.
- Required-service deletion/schema/real-S3/export selection: 49 passed.
- Backend formatting, lint, strict mypy and all six import contracts passed for
  the production fix. The full required-service coverage suite and final CI are
  running; their outcomes must be checked before merge.

The earlier chronology disclosures remain unchanged. This fix does not expand
into #90, #93 or the remaining #228 work.
