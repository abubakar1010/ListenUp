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

## Final verification

- Backend round integration: 14 passed with restricted API-role PostgreSQL.
- Full frontend suite: 655 passed. Subsequent accessibility changes are covered
  by the final focused legal/Shadow suite (54 passed).
- Full Chromium suite: 60 passed; final affected Shadow browser suite: 4 passed.
- Shadow axe scans: 3 passed (desktop, 360 px, dark theme).
- Frontend lint, types, formatting, production build and bundle budget passed.
- Backend lint, formatting, strict types and all six import contracts passed.
- Development database upgraded to head; Alembic reports no model drift.
- Uninstrumented performance test: 1 passed (development evidence only).
- Full required-service backend coverage suite is running; final result and
  changed-line coverage will be recorded in the follow-up validation commit.
- A fresh independent review remains required before merge.

Browser API responses are mocked; browser checks establish permission/media/
keyboard behavior, while restricted-role PostgreSQL tests establish server
consent enforcement. The full frontend run preceded the final small accessibility
refinements; affected tests and browser checks were rerun afterward.
