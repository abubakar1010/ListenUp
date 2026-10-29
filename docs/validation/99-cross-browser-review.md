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

## Merge blockers retained

The owner explicitly required the review's remaining validation/policy gaps to
be resolved before merge. This is not acceptance of the existing limitations:

- Real Safari on macOS/iOS and Chrome on Android, including recording/replay and
  second-device progress, have no new device evidence from this environment.
- macOS WebKit skips the AT-5 card tests and native-select keyboard coverage.
- Firefox's preview lower bound is still relaxed for the known wall-clock
  stopping defect; no product fix is included in this test-only remediation.
- The existing intermittent WebKit admin retry failure remains disclosed; a CI
  retry does not establish that it was fixed.
- The nightly/manual matrix does not gate automatic deployment. The owner's
  release-policy question remains unresolved.

Keep #99 and PR #252 open until the required evidence and policy decisions are
available. A green automated run alone does not resolve these blockers.
