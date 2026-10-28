# Story #81: Shadow round recording, private upload and replay

## Scope and prerequisites

- Builds on merged #77, #78 and #79 (ADRs 0057, 0063, 0069), on current main `6e83ba2`.
  Branch `feat/81-shadow-round-recording`. Owner approved the plan, the
  `.../rounds/{number}/recording` upload path and "a failed upload does not block the
  plan" before implementation. No worktree or delegated agent was used.
- FR-SH-5, FR-SH-8, FR-SH-16, FR-SH-17, NFR-SEC-2, AT-16. [ADR 0070](../adr/0070-shadow-round-recordings.md)
  records the schema, keys and lifecycle.
- ADR 0050 option a: `POST /shadow/rounds/{id}/complete` marks the round recorded and
  uploaded; no analysis is enqueued and no speech provider is called (ADR 0010). The
  learner sees "Feedback unavailable". #87 (plan completion) and #93 (retention sweep)
  are not built here; the Shadow step stays open.

## Acceptance and failure cases

| Requirement | Named tests |
| --- | --- |
| AT-16: three rounds, three saved replayable recordings | API `test_three_rounds_produce_three_replayable_recordings` (keys under `users/<id>/shadow/`, Opus/WebM and AAC/MP4, signed 120 s redirects, three rows uploaded, step still open). Web `records from the count-in to the end, uploads it and replays it next to the original`. E2E `three Shadow rounds use keyboard controls…` (fake microphone: three uploads, three replay regions at 360 px). |
| Other learner gets 404 | `test_other_learner_gets_404_on_recording` (GET, complete, upload request); the three routes are `Owned` in `access_registry.py`, so `test_access_cross_learner.py` checks them too. |
| MIME and size validated (`audio/webm` or `audio/mp4`, up to 5 MB) | `test_recording_mime_and_size_validated` (4 cases), `test_limits_and_codec_parameters` (5 MB accepted, codec parameters stripped), `test_stored_object_must_match_the_declared_size_and_type` (missing, wrong size, wrong type; mismatching object deleted), `test_database_keeps_recordings_private_and_write_once`. |
| Failed upload retried without re-recording | Web `retries a failed upload without recording again` (one recorder, one `getUserMedia`, two PUTs). API `test_failed_upload_retried_without_rerecording` (same key, idempotent complete, `recording_exists` afterwards). |
| Consent, order, step gate (FR-SH-17) | `test_recording_needs_consent_ended_playback_and_the_shadow_step`. |
| Browser support, Safari | Web `records AAC in MP4 where Opus in WebM is not supported`, `says so and lets the plan go on when the browser cannot record`, `discards the recording when the round is stopped`. |
| Unrecorded round | `test_unrecorded_round_has_no_replay_and_cannot_complete_without_an_upload_url`. |

## Actual test-first evidence

| Cycle | Observed Red | Green |
| --- | --- | --- |
| API recording flow | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_shadow_recording.py -q --maxfail=1`: aggregate test failed on the missing endpoint (404 on `POST .../rounds/1/recording`). Tests were written before implementation. | 11 passed after migration, models, service and routes; 12 with the later unrecorded-round test. |
| Web recording | `pnpm vitest run src/features/shadow/ShadowRecording.test.tsx`: 5 failed / 0 passed (no recorder, no upload, no replay). | 5 passed; whole shadow folder 57 passed. |

Not test-first, stated plainly: the seed/registry additions, the updated assertion in
`test_export.py` (the shared seed now has a locked segment and three rounds), the e2e
mock changes, generated OpenAPI/client files and formatting. The two uncovered
service lines are defensive races (row vanishing between the unlocked and locked read).

## Independent review

`/code-review medium` on the branch found eight issues; six were fixed test-first and
two declined. Red results before the fixes: API `test_asking_again_with_another_type_deletes_the_unreferenced_object`
and `test_completion_is_refused_and_the_upload_dropped_after_consent_is_withdrawn` failed;
web `recording.test.ts` (a microphone still opening started a recorder after the round
ended) and `treats a round whose completion response was lost as saved on retry`
(409 `recording_exists` was a permanent error) failed. All pass now. Also fixed without a
new test: the stale upload-error panel (hidden once recorded), starting the next round
while an upload is pending (button busy), and the duplicated session lock and step
check (now only in the route). Consent is checked after the ownership 404 so a second
learner still gets 404. Declined: a repeated `complete` after a size mismatch reports
`upload_incomplete`, which is accurate because the object was deleted.

## Checks run

- API: `uv run pytest -m 'not performance'`: 2338 passed, 12 skipped (S3 storage not
  reachable here, so the real-S3 integration tests skipped; CI requires them), one
  failure (`test_export…`) caused by the new seed, fixed; its file plus the access and
  recording suites then passed. After the review fixes the access, recording, rounds and
  unit suites (1338) passed again; the full API suite was not re-run end to end. `ruff check/format`, `mypy` (207 files), `lint-imports`
  (6 kept), `alembic upgrade head`, `alembic check` and a downgrade/upgrade round trip
  are clean. Changed-code coverage of `modules/shadow`: api 97%, repository 97%,
  service 93% (uncovered: defensive lines above).
- Web: `pnpm lint`, `format:check`, `typecheck`, `pnpm test:coverage` (720 passed),
  `pnpm build`, `pnpm size` (126.2 kB of 200 kB), `pnpm e2e` (247 passed, 2 skipped as
  before) all pass. One run of the full web suite after the review fixes failed once in
  `ShadowRounds.test.tsx` (bounded playback end) and passed on three isolated reruns
  and a second full run; it is timing-sensitive under load, not changed by this story.
- Accessibility: the replay controls are native `audio` elements with labels; round
  status stays in the single polite region (UX-22); axe specs for Shadow still pass.

## Follow-ups (not in this PR)

- Retention deletion after 90 days (#93) and including recording files in the data
  export (#92 follow-up).
- Analysis enqueue on lane 1 and the grade UI (#80/#82); plan completion (#87).
