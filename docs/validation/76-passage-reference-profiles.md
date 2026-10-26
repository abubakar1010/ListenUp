# Story #76: limited original reference profiles

Owner approved the plan before implementation. The session uses the isolated checkout
on `feat/76-passage-reference-profiles`, initially from main `2281d73`, reconciled to
main `5db1333` before final checks, then merged documentation-only main
`2764892` during final reconciliation (no new migrations or generated API changes). Prerequisite #45 is merged by PR #154, merge
`f2220fbb85033e24b21612e31729299bdb799d04`, verified as an ancestor. Its historical
stage-0 and independent-review gaps are not repaired or claimed passed here.

## Scope and acceptance evidence

[ADR 0061](../adr/0061-limited-reference-profiles.md) records schema, cache identity,
provenance, concurrency, failure and access decisions. ADRs 0034 and 0050 remain
unchanged. No phone GOP, learner analysis, calibrated speech scores, caption-policy
change, round implementation, card snippets or gist recovery is included.

| Criterion / boundary | Named tests and evidence |
| --- | --- |
| Original word alignment, pitch/intensity, provenance; approximately 50 KB for three minutes | `test_profile_pack_preserves_missing_words_and_absolute_times`, `test_real_pitch_intensity_and_provenance`, `test_profile_provenance_round_trip_and_atomic_readiness`, real `test_three_minute_profile_storage_under_50kb` |
| Shared learner reuse without another processing job | `test_shared_passage_reuses_profile_without_job` |
| Concurrent producers/execution | `test_concurrent_subscribers_share_one_queued_job`, `test_concurrent_profile_requests_compute_once` |
| Partial cache, retries and failures | `test_profile_ready_requires_complete_coverage_and_retry_keeps_completed_spans`, `test_failed_profile_never_announces_ready_and_retry_recovers`, `test_permanent_processing_failures_publish_only_failed` (missing audio, invalid alignment/provenance, bad acoustics, frame count, changed recipe) |
| Versioned identity and SQL integrity | `test_processing_fingerprint_changes_with_versions_and_settings`, `test_changed_recipe_creates_new_cache_identity`, `test_ready_profile_rejects_invalid_provenance` |
| Atomic readiness | `test_profile_provenance_round_trip_and_atomic_readiness`, `test_ready_event_rolls_back_with_profile`; readiness waits for complete padded coverage, events contain learner/session ids only |
| Ownership, gating, private data (including `test_profile_uses_original_words_without_learner_corrections`) | `test_profile_schema_is_worker_only`, `test_profile_access_boundaries_and_playback_independence`, `test_profile_subscriptions_are_learner_scoped`, `test_profile_queue_rejects_foreign_session_and_incomplete_transcript` |
| Nonblocking rounds contract | `test_profile_access_boundaries_and_playback_independence`, `test_failed_profile_still_allows_shadow_step_and_reports_failed`: playable content and the existing Shadow step boundary remain available with pending/failed profiles. No round module or grading UI is added; those owners consume the optional service boundary. |
| Cancellation/deletion/export | `test_profile_cancellation_cleans_scratch_and_releases_lock`, `test_deleted_media_during_processing_never_resurrects`, `test_deleted_queued_profile_is_a_noop`, `test_profile_subscription_is_in_learner_export` |
| Unobservable values and tiny spans | `test_real_silence_is_unobservable_not_perfect`, `test_short_window_retains_unknown_frames`; retain NULL rather than zero/perfect evidence or a changed pitch floor |
| Browser delivery | `useLiveEvents.test.tsx::handles every event type and ignores malformed data`, `eventKeys.test.ts::profile events refresh session grading readiness without changing playback policy` |

## Recorded Red / Green chronology

Commands below run from `apps/api` unless a web command is shown. Infrastructure or
test-setup errors were corrected and are not counted as Red evidence.

| Cycle | Focused command | Actual Red | Actual Green |
| --- | --- | --- | --- |
| Schema | `uv run pytest tests/integration/test_reference_profiles.py -q` | `to_regclass(content.reference_profiles)` returned NULL: 1 failed | 1 passed |
| Packing and trusted version identity | `uv run pytest tests/unit/test_reference_profile.py -q` | 7 failed: missing packing interface / gateway deployment identity | 7 passed |
| Acoustic adapter | `uv run pytest tests/contract/test_profile_acoustics.py -q` | 2 failed: missing adapter, after installing real Parselmouth | 2 passed |
| Shared jobs | `uv run pytest tests/integration/test_reference_profiles.py -q` | 4 missing-interface errors for `profile_jobs`, 1 existing schema pass | 5 passed |
| Authorized reads | same integration file | 1 failed: missing `reference_profile`, 8 passed | 9 passed |
| Browser | from `apps/web`: `pnpm vitest run src/events/useLiveEvents.test.tsx src/app/eventKeys.test.ts` | 2 failed, 13 passed: profile events not subscribed/mapped | 15 passed |
| Provenance integrity | same integration file | 4 malformed ready provenance values accepted; a separate unscoped job-count assertion was corrected, not treated as behavior Red | 19 passed |
| Tiny windows | `uv run pytest tests/contract/test_profile_acoustics.py -q` | 1 failed, 2 passed: Praat refused a 20 ms span | 3 passed |
| Export | `uv run pytest tests/integration/test_reference_profiles.py -k subscription_is_in_learner_export -q` | 1 failed: subscription table missing from export | 1 passed |
| Cache-word identity in public evidence | `uv run pytest tests/integration/test_reference_profiles.py -k access_boundaries -q` | 1 failed: missing `passage_transcript_id` | covered by final integration suite |

Supplemental tests for rollback, deletion, cancellation, several defensive processing
validation branches and real processing were added after those implementations;
they are characterization/strengthening evidence, not a claim of separate test-first
chronology. The missing-interface cycles preceded their implementations, but did not
individually exercise every later defensive branch. Mutation evidence below checks
that key ownership, reuse and complete-readiness assertions reject plausible defects.
Documentation/generated output requires no artificial Red.

## Real processing, kept separate from mocks

The ordinary orchestration suite injects fake alignment/storage/extraction boundaries;
its passes establish contracts, not real model output. The integration deployment
metadata fixture explicitly selects the fake model to avoid loading speech weights
while queueing jobs in unrelated tests. Real acoustic contract tests use actual
Parselmouth on deterministic tone/silence audio.

The opt-in `tests/integration/test_reference_profiles_real.py` run used:

- Public-domain LibriSpeech test-clean speaker/chapter `6930/75918`, successive full
  utterances (no repetition/cut utterances), 178.8850625 seconds of speech, padded
  with silence to 185 seconds. Selection is 0–180 seconds with trailing padding.
- Human corpus words seeded as the transcription input; seed word timings are
  synthetic. This is **not** evidence of real transcription or labelled boundary
  accuracy. #76 recomputes all word alignment from audio.
- Production `ai.yaml`, real gateway/accounting, CPU torch/torchaudio 2.8.0,
  `WAV2VEC2_ASR_BASE_960H`, 30-second windows, dynamic int8, two threads;
  real ffmpeg, Parselmouth 0.4.7/Praat 6.1.38, S3, PostgreSQL worker role,
  persistence and committed readiness.
- **1 passed**, 479/479 input words represented, 9,250 frames, **35,776 bytes**
  using `pg_column_size(profile_row)`, including packed data and metadata.
  This is composite-row storage, not JSON transport size or total table/index size.
  Corpus/input hashes and actual provenance are in
  [real-processing.json](76-reference-profiles/real-processing.json).

Command from `apps/api` (a separate speech environment keeps CPU torch out of the
normal development dependency lock):

```sh
LISTENUP_REAL_PROFILE_FIXTURE=/workspace/ListenUp/work/76-real \
LISTENUP_REQUIRE_DB=1 LISTENUP_REQUIRE_S3=1 \
TORCH_HOME=/workspace/ListenUp/work/76-real/models \
../../work/76-real/venv/bin/python -m pytest \
  tests/integration/test_reference_profiles_real.py -q
```

The preparation manifest records utterance ids and SHA-256 hashes. Recreate the
fixture from `https://www.openslr.org/resources/12/test-clean.tar.gz`, concatenate
those FLACs in listed order as 16 kHz mono PCM, pad silence to 185 seconds, and
supply `reference.wav`, `words.json` and `source.json` under the fixture directory.
The opt-in test is explicitly skipped in normal CI without this fixture; its
separate successful real run above supplies the processing/size evidence.

## Performance and quality limits

**Deferred until staging — unverified:** actual stage-0 performance, tracked in
[#155](https://github.com/abubakar1010/ListenUp/issues/155), with #16 provisioning
and the unchanged System Design §12 real-server workload/targets. Container test
elapsed time is not a latency acceptance result. #45's playable-to-transcribed
p95 <120 seconds and #21's real-round latency gates remain unchanged/unverified.

ADR 0034's independent, complete human-label boundary gate remains unverified.
Neither this storage test nor inter-model agreement satisfies it. ADR 0050's
no-go for calibrated grades, launch gates (#21/#22/#110), and deferred #80 phone
work remain intact. This story does not enable learner grading.

## Final validation

- Focused final backend run with PostgreSQL/S3 required: **66 passed**. The later
  private-correction characterization test separately passed. This is a targeted
  run, not a whole-repository coverage baseline.
- Complete backend runtime inventory passes. Changed executable backend coverage:
  **281/290 lines (96% as reported by diff-cover)**; no exclusions weakened.
  Nine uncovered defensive lines cover unknown deployment/library versions,
  the real extraction wrapper (exercised in the separate uninstrumented real run),
  absent profile/active source, disabled subscribers, and readiness reads before
  subscription/with missing transcript coverage. SQL integrity, denial, partial
  readiness, rollback and relevant failure assertions are exercised.
- Ruff lint/format, strict mypy (199 source files), all six import contracts,
  migration upgrade/drift/downgrade/re-upgrade, and API export/client generation pass.
  No new HTTP route was introduced; access-registry coverage remains applicable.
- Web lint/format/types and production build pass. Initial JavaScript is
  **125.6 KB gzip / 200 KB budget**. Local Playwright: **54 passed** against mocked
  API responses; this is not a full live-stack browser test.
- Real processing/size evidence and limitations are recorded above.

Local broad-check failures are retained rather than relabelled as passes:

- The first concurrent web coverage attempt reported failures in existing
  Dictation/Transcript-mark tests and was interrupted for diagnosis. A clean
  `origin/main` snapshot passed all 64 tests in those two files under coverage.
- The full one-worker web run completed with **607 passed / 2 failed**: five-second
  timeouts in existing `BusyButton` and `BlindStep` tests. It reported line coverage
  96.13% and branch coverage 88.72%; those totals do not make the failed run pass.
  A subsequent run during other local checks also encountered existing UI failures.
  No mode module, assertion, timeout or threshold was changed to hide these results.
- The original local whole-backend run ended without a final summary after the
  environment interruption. It is **incomplete**, not passed.
- The local uninstrumented existing Dictation budget test failed: best 0.462 s
  against its unchanged 0.2 s limit while other checks ran on this two-CPU executor.
  This is an existing scoring budget, not stage-0 profile performance acceptance.

CI performs the full backend/web suites, uninstrumented budget, complete/changed
coverage, all images, real sandbox/scanner, generated client, vulnerability scan,
AI smoke, observability and Playwright checks on the pushed branch. The PR checks
and [branch workflow runs](https://github.com/abubakar1010/ListenUp/actions?query=branch%3Afeat%2F76-passage-reference-profiles)
provide the final-head results; local failures above remain disclosed even when
those checks pass. The initial source push is
[run 40230431319](https://github.com/abubakar1010/ListenUp/actions/runs/40230431319).
Fresh-session independent review has not been performed and is required before merge.

Mutation checks used copied source trees under `work/76-mutations`, without editing
the active checkout or creating a Git worktree. Each mutation was caught by an
assertion failure (exit 1):

- Remove the explicit privileged-caller ownership guard →
  `test_profile_access_boundaries_and_playback_independence` fails.
- Remove the ready-cache early return →
  `test_profile_provenance_round_trip_and_atomic_readiness` detects repeated inference.
- Replace complete-profile `all(...)` with `any(...)` →
  `test_profile_ready_requires_complete_coverage_and_retry_keeps_completed_spans`
  detects premature readiness.

`uvx --from uv==0.8.24 uv lock --check` also passes, checking compatibility with the
media Docker image's uv 0.8 toolchain. The normal environment uses uv 0.12.23.
