# Cross-browser review remediation (#99, PR #252)

This is test infrastructure only: no application behavior, migration or API
change. The suite mocks the API and does not prove server-side Blind enforcement.

## Findings and regression checks

- Recording capability loss must fail on required runners. The only allowed
  capability exceptions are Linux WebKit without MediaRecorder and Firefox
  without MP4 for the MP4 variant. `recording-policy.spec.ts` covers these
  exceptions, required capability failures, and supported capabilities. Edge
  uses Playwright's Chromium browser name and follows that policy.
- Every omitted CSRF-header or Blob-body assertion is now a named skipped
  Playwright step with a `skipped-check` annotation and reason. Passing the
  surrounding flow does not claim the omitted check passed.
  `check-reporting.spec.ts` verifies the annotation, that skipped checks do not
  run, and that an available check's failure still propagates.
- The local runbook runs Chromium/Edge without PulseAudio and Firefox separately
  with its null sink; no workflow trigger or runner setup changed.

## Actual red/green evidence

Before implementing the policy and reporting helpers, added the named regression
tests. The focused command below failed because `browserCheck` was not exported
and the new recording policy interface was missing. This is an intentionally
missing test-harness interface, not product-behavior Red or infrastructure failure.

The scratch configuration at `work/playwright-policy.config.ts` contained:

```ts
import config from '../apps/web/playwright.config';
export default { ...config, webServer: undefined, testDir: '../apps/web/e2e' };
```

From the repository root, both Red and Green used:

```sh
pnpm --dir apps/web e2e recording-policy.spec.ts check-reporting.spec.ts \
  --project=chromium --workers=1 --config ../../work/playwright-policy.config.ts
```

After implementing the helpers, all 12 focused tests passed. The tests need no
browser or application server. A subsequent run with `--reporter=json` also
confirmed the `skipped-check` annotation in the output. This evidence applies to
the review remediation only; it does not establish chronology for the original
PR's reported mutations.

The runbook is documentation and does not need artificial Red. Lint, formatting,
type checking, build and size checks passed locally. Initial JavaScript was
126.7 KB gzip against the 200 KB budget. Full-suite results and exact CI links are
recorded in the PR after the remediation push. No production executable lines
changed; the changed-line coverage gate still runs in CI.

## Outstanding validation and later merge authorization

The owner initially required the review's remaining validation/policy gaps to
be resolved before merge, then explicitly instructed merging the PR after the
remediation and successful checks. That later instruction authorizes the merge;
it does not establish that these checks passed or resolve release policy:

- Real Safari on macOS/iOS and Chrome on Android, including recording/replay and
  second-device progress, have no new device evidence from this environment.
- macOS WebKit skips the AT-5 card tests and native-select keyboard coverage.
- Firefox's preview lower bound is still relaxed for the known wall-clock
  stopping defect; no product fix is included in this test-only remediation.
- The existing intermittent WebKit admin retry failure remains disclosed; a CI
  retry does not establish that it was fixed.
- The nightly/manual matrix does not gate automatic deployment. The owner's
  release-policy question remains unresolved.

Keep #99 open for the required evidence and policy decisions. The earlier
instruction to keep PR #252 open was superseded by the owner's merge instruction.
A green automated run alone does not establish the missing device evidence.

## Readiness race found during merge validation

Push CI run 40884988278, attempt 2, on `7eec600` failed in
`ShadowRecording.test.tsx`: `discards the recording when the round is stopped`
could not find `Stop round 1` (737 tests passed, 1 failed). Its one-shot
`loadedmetadata` event could precede the player's effect attaching the listener,
so the subsequent Play click could hit a disabled button. The nearby
`playRound` helper already handles that ordering.

The test now waits for enabled Play while supplying metadata and verifies an
active recorder before Stop. The track-stop and no-upload assertions remain.
This repairs the test setup without changing product code or relaxing a check.

Observed failure before this edit: `pnpm test:coverage` in the CI run above.
After the edit, `pnpm exec vitest run
src/features/shadow/ShadowRecording.test.tsx` passed all 8 tests. The focused
format check and `pnpm typecheck` also passed. Final full CI results are in the
PR. The initial cancelled push run and its failed rerun remain disclosed;
neither is claimed as a pass or a fix by retry.
