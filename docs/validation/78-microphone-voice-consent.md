# #78 microphone and voice consent validation

## Scope and acceptance mapping

The existing #79 round-start boundary was inspected first. #78 reuses it; there
is no recording, upload, replay, grading, migration or plan-completion change.
See ADR 0065 for the #81 interface and resource/consent lifecycle.

| Requirement | Evidence |
| --- | --- |
| FR-SH-7: permission failure recovery | `ShadowReadiness.test.tsx`: denied, missing and busy inputs; silence; audible input; speech with pauses; disconnected input |
| Accessible levels and headphones advice | Labelled native meter; polite state status; real Chromium fake microphone and native keyboard activation in `e2e/shadow.spec.ts` |
| FR-SH-17: current version and explicit grant | `shows the current legal text and requires explicit agreement`; stale/withdrawn rows; unknown and inherited legal-registry labels fail closed |
| Server enforcement and idempotency | `test_voice_consent_required_before_start_and_replay`; `test_stale_voice_consent_refuses_new_start_and_saved_replay` |
| Ownership and step gate | Existing `test_round_ownership_is_enforced_by_composite_fk_and_rls`, step/skip tests and the cross-learner access suite; ownership/step checks precede consent |
| Withdrawal recovery in an open page | `returns to explicit consent when the server refuses a cached consent at start` |
| Restored page requires readiness | `ShadowGate.test.tsx`: blocked start and restored playback |
| Resource races | Late permission after unmount/cancel, hidden page, disconnected track and timeout tests |
| Confirmed Skip Shadow | Browser test denies real browser permission, uses Enter on Check/Skip, observes safe dialog focus and sends confirmed skip only after activation |
| ADR 0050 and #81 scope | Existing three-round tests retain null `recorded_at`, no completion event and Feedback unavailable |

## Actual TDD evidence

- Red: `.venv/bin/pytest tests/integration/test_shadow_rounds.py -k voice_consent --no-cov -q`
  failed because an unconsented start returned 204 rather than 403.
- Green: `.venv/bin/pytest tests/integration/test_shadow_rounds.py --no-cov -q`
  passed all 14 tests after enforcement and additional stale-version coverage.
- Red: `pnpm vitest run src/features/shadow/ShadowReadiness.test.tsx` initially
  failed on the deliberately absent readiness component interface.
- Green: the initial four permission/legal-text tests passed after implementation.
- Red: `pnpm vitest run src/features/shadow/ShadowReadiness.test.tsx -t 'repeated speech'`
  failed to detect input separated by pauses. Chromium's default fake microphone
  also exposed this behavior.
- Green: after counting audible samples across pauses, the focused Shadow suite
  passed 40 tests and the fake-media three-round browser test passed.
- Further lifecycle, cached-consent and composition cases were added after the
  initial component implementation. They are supplementary regression coverage,
  not claimed as independent test-first cycles.

- Red/green: `pnpm vitest run src/features/legal/LegalText.test.tsx -t 'embeds a consent'`
  first failed because embedded legal headings remained h1/h2. After adding an
  optional heading offset (standalone legal pages retain their headings), the
  legal/Shadow suite passed 49 tests.

- Red/green: the explicit-grant test failed when focus stayed on the body;
  it passed after focusing the accepted-consent notice. A separate `browser mutes`
  regression failed while readiness stayed true, then passed after adding the
  muted-track handler.

- Red/green: `pnpm vitest run src/features/shadow/ShadowReadiness.test.tsx -t 'during activation'`
  failed because AudioContext.resume was deferred until after permission. The
  final flow resumes in the button activation before awaiting getUserMedia;
  the focused legal/Shadow suite then passed 55 tests.
- The new unknown-legal-text axe state first failed because the test API always
  returned its default version. Its default now yields to a state's explicit
  answer; all 15 Shadow axe states pass without exceptions.

## Final verification

- Backend round integration: 14 passed with restricted API-role PostgreSQL.
- Full frontend suite: 655 passed. Subsequent accessibility changes are covered
  by the final focused legal/Shadow suite (55 passed).
- Full Chromium suite: 60 passed; final affected Shadow browser suite: 4 passed.
- Shadow axe scans: 15 passed (five states across desktop, 360 px and dark theme).
- Frontend lint, types, formatting, production build and bundle budget passed.
- Backend lint, formatting, strict types and all six import contracts passed.
- Development database upgraded to head; Alembic reports no model drift.
- Uninstrumented performance test: 1 passed (development evidence only).
- Full required-service backend suite: 2,218 passed, one optional real-profile
  test skipped because LISTENUP_REAL_PROFILE_FIXTURE was not configured, and
  the performance test deselected for its separate run. PostgreSQL and S3 were
  required and available.
- Latest-main additions: 87 passed (collected after the full run had started),
  with coverage combined into the backend report. Total functional tests:
  2,305 passed, one optional real-model fixture skipped.
- Final round/segment integration rerun: 32 passed. The server file moved by
  one line during schema cleanup; its stale coverage measurement was discarded
  before this rerun so the final report measures the current source accurately.
- Changed executable lines: backend 100%, frontend 98%; both complete runtime
  source inventories pass check-coverage.py. Two uncovered frontend lines are
  defensive cleanup after a pending AudioContext.resume resolves following
  cancellation; late permission-result disposal and ordinary cleanup are tested.
- The initial push was blocked by automatic approval review pending explicit
  authorization. The owner subsequently authorized publishing the branch and
  opening a draft PR; remote CI results are tracked on that PR.
- A fresh independent review remains required before merge.

Browser API responses are mocked; browser checks establish permission/media/
keyboard behavior, while restricted-role PostgreSQL tests establish server
consent enforcement. The full frontend run preceded the final readiness and accessibility
refinements; affected tests and browser checks were rerun afterward.

Screen-reader support is checked through semantic roles, labelled meter,
state-only live announcements and axe; a manual assistive-technology session was
not performed. Recording/upload/replay remain excluded and grading stays
unavailable under ADR 0050.
