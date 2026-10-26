# #98 part 1: automated axe checks on every route

Scope: the automated part of [#98](https://github.com/abubakar1010/ListenUp/issues/98)
for screens that exist on `main`. #98 depends on #87 and #75 and stays open for the
manual screen-reader passes, keyboard runs of complete plan paths (AT-7) and the
accessibility statement. Serves NFR-USE-2, UI-3 and UI-4.

## What runs

- `apps/web/e2e/a11y.spec.ts` visits every state in `e2e/a11y/states.ts` (45 states
  covering all routes in `src/App.tsx`) and runs axe-core 4.14 through
  `@axe-core/playwright` with the tags `wcag2a`, `wcag2aa`, `wcag21a` and `wcag21aa`.
- Serious and critical violations fail. Moderate and minor ones, and the checks axe
  could not decide (`incomplete`), are attached to the Playwright report as
  `axe-results.json` for each state (no violations were found).
- Each state must be the screen it names: the scan fails on a request the state does
  not answer, and on visible alert text unless the state is marked `alert`.
- Three Playwright projects run the spec: `a11y-desktop` (1280 × 800, light),
  `a11y-360` (360 × 740, light) and `a11y-dark` (1280 × 800, dark). All three use
  reduced motion so axe never measures a transition midway. At 360 px each state also
  fails on sideways page scrolling (UI-4).
- The API is answered in the browser by `e2e/a11y/fakeApi.ts`. Its fixtures are typed
  with `satisfies` against `src/api/schema.ts`, so a schema change that they no longer
  match fails `pnpm typecheck`. This proves the rendered pages against those answers,
  not the live stack.
- `pnpm e2e:a11y` runs the three projects. CI runs them in the **Accessibility (axe,
  Playwright)** job and keeps the HTML report as the `a11y-report` artifact for 14
  days; the smoke job now runs only the `chromium` project, so nothing runs twice.

## Route and state inventory

| Area | States |
| --- | --- |
| Signed out | sign-in; refused; paused (429 `account_locked`); register; register field errors; forgot password; reset link sent; reset password; reset link incomplete; account deleted; terms; privacy; voice consent; Google error; page not found |
| Library and intake | empty library; library with ready, converting and failed clips and a plan; add clip; daily limit reached; clip ready; clip converting; removed duplicate copy; clip not found; start plan; part of a clip with the waveform handles |
| Account | settings; settings with an export ready; delete account; consent owed (ADR 0048) |
| Admin | jobs with a failed job; usage |
| Session | Blind ready to start; Blind gist form; Blind attempt ended; plan sheet (360 px only); Dictation typing; Dictation scored beside Transcript; Transcript with marks and its mark note editor (Dictation entry, so without #70's gist panel); skip-Card confirmation; plan finished |
| Owned by open stories | Blind gist feedback beside Transcript and before Dictation ([#70](https://github.com/abubakar1010/ListenUp/issues/70)); Card ([#73](https://github.com/abubakar1010/ListenUp/issues/73)); Shadow segment ([#79](https://github.com/abubakar1010/ListenUp/issues/79)) |

The plan sheet exists only at narrow widths, so its desktop and dark runs are skipped
by design (2 skipped tests).

## Exceptions

Owner decision for this PR: the screens owned by #70, #73 and #79 are scanned and
gated like every other screen, because they have no violations today. Their source
files are not edited here. If one of those stories introduces a violation that it
cannot fix in the same PR, it adds an entry to `e2e/a11y/allowlist.ts`.

Each allowlist entry names the rule, the state, a reason and the issue URL, and may
name the projects it applies to (for a violation only one width or theme shows). The
spec fails when an entry has no reason, links no GitHub issue, links an issue other
than #70, #73 or #79, names a state that is not owned by that issue, names an unknown
project, or no longer matches a violation, so the list only shrinks. A scan state may
name only those three issues as its `owner`. A
temporary mutation (one stale entry on `card`, one entry with a blank reason and no
issue on `sign-in`) failed both checks as expected and was reverted.

The allowlist is empty.

## Before and after

Before (triage on `main` at `5db1333`, then the new spec before the fixes):

| Rule (impact) | Element | Cause |
| --- | --- | --- |
| `label-content-name-mismatch` (serious, WCAG 2.5.3) | Transcript word button, `src/features/review/TranscriptScreen.tsx` | Visible "Cities" + "Edited" with no space between; the name "Jump to Cities (edited)" does not contain the visible words in axe's comparison |
| same | Mark play button, `src/features/review/MarkList.tsx` | Visible "00:11 · Again." but named "Play mark Again. at 00:11" |
| same | Mark "Edit note" button, same file | Named "Edit mark Again.", which drops "note" |

Red: `pnpm e2e:a11y` → 12 failed (Dictation scored beside Transcript, Transcript with
marks, mark note editor and Blind gist feedback beside Transcript, each in the three
projects), 124 passed, 2 skipped. All failures were this rule on these elements.

The first triage pass ran axe on the final state of all 54 existing Playwright tests
(light and dark) and on 20 routes at 1280 and 360 px. It also reported
`document-title` and `html-has-lang` on `about:blank` and on a page the Google spec
serves itself; those are not application pages and the new spec does not scan them.
No contrast failures were found in either theme.

After:

- `src/features/review/MarkList.tsx`: the play button's name is its visible text with
  a visually hidden "Play mark" before it and the separator dot hidden from screen
  readers ("Play mark 00:11 Again."); the edit
  button is "Edit note for mark Again.".
- `src/features/review/TranscriptScreen.tsx`: an edited word is named
  "Jump to Cities, edited" and its visible text has a real space before "Edited".
- Green: `pnpm e2e:a11y` → 136 passed, 2 skipped. Across the 130 scans axe reported no
  violations of any impact.
- `pnpm e2e` (all projects) → 190 passed, 2 skipped.

## Test-first evidence

| Behavior | Test | Red | Green |
| --- | --- | --- | --- |
| No serious/critical axe violation on any state, at three viewports | `e2e/a11y.spec.ts` › `axe: <state>` | 12 failed, as above | 136 passed, 2 skipped |
| Mark buttons are named by their visible text | `MarkList.test.tsx` › `list_buttons_offer_edit_remove_and_ignore_modified_or_repeated_shortcuts` | `pnpm vitest run src/features/review/MarkList.test.tsx`: no button named "Play mark 00:00 · (removed words)" | passes |
| An edited word reads "word Edited" and is named "Jump to word, edited" | `TranscriptScreen.test.tsx` › `shows_learner_edits_and_removed_words_with_original_audio_targets` | text content "GreetingsEdited"; then no button named "Jump to Greetings, edited" | passes |
| Allowlist entries are complete, owned and current | `e2e/a11y.spec.ts` › `every allowlist entry has a reason, an issue and an owned scan state`, stale check in each `axe:` test | temporary mutation, above | passes with an empty list |

The first fix to the word button (adding the space only) left the e2e scan red; a
direct axe probe showed that "(edited)" in the name is what fails the comparison, and
", edited" passes. The existing e2e specs that used the old names
(`transcript.spec.ts`, `dictation.spec.ts`) were updated to the new names.

## Review follow-up

An independent review of `17dc409` found states that did not reach the screen they
name, and looser allowlist rules than the policy. Fixed on this branch:

| Finding | Fix |
| --- | --- |
| `terms`, `privacy`, `voice consent` showed "The text of version 2026-10-01 is not available here." | The fake sends the real labels (`terms-2026-1` and so on); `ready` waits for the version line of the text itself |
| `reset password` showed "This reset link is incomplete" (the token is read from the hash) | `path` is `/reset-password#token=abc`; the incomplete link is its own `alert` state |
| `shadow segment` (#79) showed "We could not find this" for `/shadow/rounds` | Answers for the rounds and the peaks |
| Fakes off the schema: partial `BlindStep`, words without `edited`, `void_reason: 'left'`, `last_session_status` on `ContentDetail` | Fixtures typed with `satisfies`; `blindStep()` builds the full answer |
| Any `owner` could hold an exception; no per-project entries; `blind gist feedback beside transcript` (#70) was the same page as `transcript with marks` | `OWNERS` holds only #70, #73 and #79; optional `projects`; the Transcript states use the Dictation entry |
| `incomplete` axe results not kept | Attached with the violations |
| The play button's name included "·", which screen readers announce | The dot is `aria-hidden`: "Play mark 00:11 Again." (still contains the visible words in axe's comparison) |

Red, then green:
- `pnpm e2e:a11y --project=a11y-desktop` with the new alert and unanswered-request
  checks and the old fixtures: 12 failed. Five were real (the three legal pages, reset
  password, Shadow segment); seven were error states not yet marked `alert`. After the
  fixes, `pnpm e2e:a11y`: 145 passed, 2 skipped.
- `MarkList.test.tsx`: no button named "Play mark 00:00 (removed words)", then passes.
- The allowlist tests were written with the rules. Three temporary mutations (dropping
  the `OWNERS` check on entries, on states, and the `projects` filter) each failed
  `allowlist problems name each broken rule` or `only screens owned by #70, #73 or
  #79 may hold exceptions`; all reverted.

## Final checks

`pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test:coverage` (60 files,
638 tests), `pnpm build`, `pnpm size` (125.6 kB of 200 kB) and `pnpm e2e` (204 passed,
2 skipped) all pass locally after the review follow-up. No backend, API or schema change.

## Still open in #98

- Manual keyboard and screen-reader passes (one desktop and one mobile reader)
  through all three plan paths, including marks, cards and Shadow rounds (AT-7).
- Live regions for status, grading and voiding, checked with a screen reader.
- Shadow recording rounds, Card review and the screens #70, #73, #79, #87 and #75
  are still building: add their states to `e2e/a11y/states.ts` as they land.
- The accessibility statement.
- axe checks WCAG 2.1; the design log targets WCAG 2.2 AA (target size, focus not
  obscured), which needs the manual pass.
