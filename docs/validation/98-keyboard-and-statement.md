# #98 part 2: keyboard plan paths, 360 px, live regions and the statement

Scope: the rest of [#98](https://github.com/abubakar1010/ListenUp/issues/98) after
part 1 ([98-axe-route-checks.md](98-axe-route-checks.md), #213). Serves NFR-USE-2,
UI-3, UI-4 and AT-7. #87 and #75 are closed. No backend, API, schema or migration
change. Nothing in `src/features/shadow` was edited, because #82 is changing those
files. The Shadow fixes needed are listed under [Reported for #82](#reported-for-82).

## Acceptance criteria

| Criterion | Evidence | Status |
| --- | --- | --- |
| axe reports no serious or critical violations on any route | `e2e/a11y.spec.ts` (part 1), now also on `/accessibility`: `pnpm e2e:a11y` 202 passed, 2 skipped (the plan sheet exists only at 360 px) | Met (automated) |
| A keyboard-only user can complete each plan path (AT-7), including marks, cards and Shadow rounds | `e2e/keyboard-paths.spec.ts` › `keyboard only: the {blind, dictation, both} path to the finished plan at {1280, 360} px`: 6 passed | Met in Chromium against a mocked API, with one recorded Shadow focus gap (below). The manual keyboard and screen-reader passes are the owner's checklist, not run |
| Every screen works from 360 px wide (UI-4) | Sideways scrolling is checked on every scan state (part 1) and on every screen of the keyboard runs; the new 44 px target check covers every state at 360 px (`axe: <state>` in `a11y-360`) | Met (automated), one Shadow target reported |
| Live regions for status, grading and voiding (scope) | Audit below; `DictationResultPanel.test.tsx` › `a score that arrives while the panel waits is announced`, `GistFeedback.test.tsx` › `the transcript feedback status is a polite live region` | Fixed where found; announcements not yet heard in a screen reader |
| An accessibility statement (scope) | `/accessibility`, text in `docs/legal/accessibility-statement.md`; `AccessibilityStatementPage.test.tsx` | Draft, contact to complete before launch |
| Manual screen-reader checklist for the owner | [98-screen-reader-checklist.md](98-screen-reader-checklist.md) | Written, **not run** |

This PR uses "Refs #98": the manual screen-reader passes are not done, and #98 stays
open for them.

## Keyboard runs of the plan paths

`e2e/keyboard-paths.spec.ts` starts in the library and finishes each path. Every
control is reached with Tab (Shift+Tab for the Blind checkbox, which comes before
Dictation), never with `focus()` or a click, and is used with Enter, Space, arrows or
typing. The helpers in `e2e/keyboard/keys.ts` fail when:

- a Tab stop shows no focus indicator, an outline of at least 2 px or a box-shadow ring
  (WCAG 2.4.7). Native `<audio controls>` is exempt: Chromium draws the ring on the
  control's inner buttons, which `getComputedStyle` cannot see (manual check 7.8);
- focus is on the page body when the next control is sought (2.4.3), except right after
  a page load. Tab past the last control wraps once, as browsers do;
- the target is not reached within its number of presses;
- at 360 px the page scrolls sideways (UI-4).

Each path checks AT-7's entry rule ("Change entry" on the first step, "Entry locked"
from Transcript on), that focus is on the Transcript h1 on arrival, that the mark is
saved and confirmed (from Dictation) or made with Shift+Arrow and M (Blind only), that
a card is saved, that three rounds are uploaded, and that no Blind attempt was voided.
`e2e/keyboard/planServer.ts` is a stateful fake of the plan API, typed against
`src/api/schema.ts`. It fails the run on any request it does not answer. Like every
Playwright spec here it proves the browser against these answers, not the live stack.
The time a passage takes to play is stood in for by moving the media clock
(`playThrough`); the learner presses nothing for it. On macOS WebKit the spec is
skipped like the other specs that use a native select (`SAFARI_SELECT`).

### Red, then green

| Run (`pnpm exec playwright test keyboard-paths --project=chromium`) | Outcome | Cause | Change |
| --- | --- | --- | --- |
| Blind path, 1280 px | Failed at Card: "No marks in this session", though the server held the mark | **App bug**: Card reused Transcript's cached mark list, read before any mark was made | `fix(card)`: Card reads the marks under its own cache entry |
| All six | Failed: focus on the page body before "Continue to Transcript", "Continue to Dictation" and "Add “plant” to marks" | **WCAG 2.4.3**: Submit gist and the Dictation submit remove the focused control | `fix(plan)`: gist feedback heading takes focus; arrival at a step focuses its h1 |
| All six | Failed: focus on the body before the first Transcript control | **2.4.3**: Transcript swaps its loading screen for its content, replacing the focused h1 | Arrival focus follows the new heading for up to 3 s, until a key or pointer press |
| All six | Failed: focus on the body before "Start round 2" | **2.4.3** in Shadow, not changeable here | Recorded as a known focus loss (below) |
| All six | 6 passed (2.0 min), then 6 passed (2.1 min) with the AT-7 entry checks | | |

Errors in the spec itself, fixed while writing it and not app defects: the fake
answered the consent POST without the consents list; the focus-ring check flagged
native audio controls; Dictation-only needs Shift+Tab back to the Blind checkbox; Tab
past the last control legitimately reaches the body; a freshly loaded page has focus
on the body.

### Unit tests, red then green

| Behavior | Test | Red | Green |
| --- | --- | --- | --- |
| Card lists the marks made in Transcript when it replaces it | `CardScreen.test.tsx` › `card_lists_marks_made_in_transcript_when_it_replaces_transcript` | `pnpm vitest run src/features/cards/CardScreen.test.tsx -t card_lists_marks`: no option named "could have" | passes; `src/features/cards` and `src/features/review`: 206 passed |
| Arrival at the next step focuses its h1 | `SessionPage.test.tsx` › `arriving_at_the_next_step_focuses_its_heading` | with `SessionPage.tsx` stashed: "Expected element with focus" (the h1), received the body | passes |
| Arrival focus survives the step's loading swap | `SessionPage.test.tsx` › `arrival focus follows the heading when the step finishes loading` | the new h1 did not have focus after the transcript loaded | passes |
| A step that places focus itself keeps it | `SessionPage.test.tsx` › `a step that places focus itself keeps it on arrival` | characterization of Card's own focus, passed before the change | passes |
| After Submit gist, focus is on the feedback heading | `GistForm.test.tsx` › `after submitting, focus is on the gist feedback heading` | focus on the body | passes |

The first version of the arrival test used Skip Card. It stayed red after the fix
because `ConfirmDialog` sends focus to `<main>` when its opener has gone; that is
designed behavior and keeps focus, so the test was moved to the gist path, which has no
dialog.

## 360 px gaps

Part 1 already fails any state that scrolls sideways at 360 px. This part adds the
UX-15 target size: at 360 px every visible control's hit area must be at least 44 px
in each direction (`e2e/a11y/targets.ts`). A checkbox or radio counts its label; a
wider absolutely placed `::before` counts. Links inside running text and transcript
words are exempt, as UX-15 says.

Red (`pnpm exec playwright test a11y.spec --project=a11y-360`, gate on, fixes stashed):
almost every state failed, on these targets. Green after the fixes: `pnpm e2e:a11y`
202 passed, 2 skipped.

| Target | Size at 360 px | Fix |
| --- | --- | --- |
| "ListenUp" wordmark in every header | 92 × 28 | `inline-flex min-h-11 items-center` (`app/Wordmark.tsx`) |
| Clip title links in the library | 294 × 24 | same, `self-start` (`LibraryPage.tsx`) |
| "Back to sign in" / "Back to account deletion" (Google error) | 312 × 24 | same (`GoogleErrorPage.tsx`) |
| "← Back to settings" | 144 × 24 | same (`DeleteAccountPage.tsx`) |
| "Keyboard shortcuts" disclosure beside Transcript | 302 × 24 | `py-2.5` on the summary (`TranscriptScreen.tsx`) |
| Passage start and end handles | 40 × 44 hit area | the `::before` hit area is 14 px each side, not 12 (`Waveform.tsx`) |
| "Voice recording consent" link in Shadow | 294 × 24 | Reported for #82; listed in `KNOWN_SMALL_TARGETS`, which fails once it is fixed |

The keyboard runs also check sideways scrolling on every screen of every path at
360 px, including the Shadow rounds and the finished plan, which the scan does not
reach.

## Live regions

Audit of every `role="status"`, `role="alert"` and `aria-live` in `apps/web/src`
against UX-04 (late results announced politely where they land), UX-22 and the
announcement list in the design log.

| Kind | Where | Finding |
| --- | --- | --- |
| Status | Draft and mark save status (`DictationScreen`, `MarkPanel`), card count (`CardScreen`), Dictation marks added (`DictationMarks`), clip ready (`ClipNotices`), step count (`StepProgress`), plan size (`PlanPreview`), upload (`AddClipPage`) | Persistent live regions whose text changes. No change |
| Grading | Gist feedback after Blind | Polite, persistent. No change |
| Grading | Gist feedback beside Transcript | `aria-live="off"`, so a grade that landed while the learner reviewed was silent (UX-04). **Fixed**: polite in both places |
| Grading | Dictation score | The waiting message was replaced by the diff and nothing announced the score. **Fixed**: an empty status region from the start says "Your Dictation is scored: N%." when a score arrives while waiting; a score already there is not announced |
| Grading | Shadow round feedback | In `src/features/shadow`; the round status region is persistent. Not changed here |
| Voiding | Blind attempt ended | `role="alert"` notice (assertive, UX-22). No change |
| Voiding | Blind interruption and resume | `role="status"` sections, and Carry on now takes focus. No change |

Two existing tests in `DictationResultPanel.test.tsx` found "the" status with
`findByRole('status')`; with the second region they now find the message by its text
and check its role. What they assert is unchanged.

Red: `pnpm vitest run src/features/dictation/DictationResultPanel.test.tsx
src/features/blind/GistFeedback.test.tsx` → `the transcript feedback status is a polite
live region`, `a score that arrives while the panel waits is announced` and `a score
already there when the panel opens is not announced` failed (the last because the
region did not exist yet). Green: 135 passed in `src/features/dictation` and
`src/features/blind`.

## Accessibility statement

`/accessibility` is public, like the legal texts, and linked from Settings. The text is
`docs/legal/accessibility-statement.md`, rendered with `LegalText`. It says ListenUp is
partially conformant with WCAG 2.1 AA and does not claim screen-reader support. It also
lists the automated checks, the keyboard use, the deliberate exercise rules and the
known Shadow gaps. Its contact is a placeholder, as in the legal drafts.

Red: `pnpm vitest run src/features/legal/AccessibilityStatementPage.test.tsx` → 2 failed
(no heading, no Settings link). Green: 59 passed in `src/features/legal`,
`src/features/account` and `App.test.tsx`. Axe passes on the page in all three
projects.

## Reported for #82

These are in `src/features/shadow`, which this story may not change:

1. **Focus after a round ends (WCAG 2.4.3).** When a round's playback ends, the focused
   round control is removed and focus falls to the page body. Tab from the body still
   reaches "Start round N+1" in Chromium. Suggested fix in `ShadowRounds.tsx`: once the
   playback-ended write settles, move focus to the next action ("Start round N+1"), or to
   the round heading while the recording saves. After round 3 the session's arrival focus
   (this PR) already puts focus on the finished plan's h1. The keyboard spec records this
   as `known-focus-loss` and fails once focus is kept, so the exemption is removed with
   the fix.
2. **Consent link target (UX-15).** In `ShadowReadiness.tsx` the "Voice recording
   consent" link is a 24 px tall block link at 360 px. Suggested fix:
   `inline-flex min-h-11 items-center`. Remove its `KNOWN_SMALL_TARGETS` entry with the
   fix; the scan fails until then.
3. **Native audio focus ring.** The recording replays use `<audio controls>`. Chromium
   draws its own ring; check it manually (checklist 7.8).

## For the owner

- Placing the statement link: it is linked from Settings only. Signed-out visitors
  reach it only by its address. A footer link on every page would be a new UI element,
  so it is left for a UX decision.
- Gist submission focus: no design rule names the target after Submit gist. This PR uses
  the pattern the boards use for replaced content (focus on a tabindex −1 heading, here
  "Your gist feedback"), with Continue as the next Tab stop. Please confirm.
- The statement's contact and review date must be completed before launch.

## Final checks

Run locally from `apps/web` on the branch head, Chromium only:

| Check | Result |
| --- | --- |
| `pnpm lint`, `pnpm format:check`, `pnpm typecheck` | pass |
| `pnpm test:coverage` | 70 files, 750 tests passed |
| Changed-line coverage (`diff-cover` against `origin/main`, as in CI) | 38 of 38 changed lines covered (100%); every runtime file resolves in the report |
| `pnpm build`, `pnpm size` | pass; 126.8 kB of 200 kB initial JavaScript |
| `pnpm e2e` (chromium and the three a11y projects) | 290 passed, 2 skipped (the desktop and dark runs of the 360 px plan sheet) |

Not run here: Firefox, WebKit and Edge (the nightly cross-browser workflow runs the new
spec there; it skips on macOS WebKit like the other native-select specs), and the
manual screen-reader passes. No backend change, so no backend checks apply.
