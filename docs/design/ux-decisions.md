Source: https://claude.ai/artifact/AYRJxLdttjEKTk7ze2ZGnW (exported from https://claude.ai/code/artifact/4d45493e-2765-42b4-a9fd-3c87bea343db) · Exported 2026-10-09

# ListenUp UX Decision Log

Oct 2, 2026 · @Md. Ebrahim Hossen

This log holds every UI/UX decision behind the ListenUp final UI: what was decided, why, what else was considered, and the SRS requirement IDs it serves. Developers follow these decisions; product rules stay with the PRD and SRS.

**Update 2026-10-03.** The user approved every product recommendation (decisions D1 to D15). Proposals P-1 to P-4 are accepted, every open product question is decided, and the UI canvas now shows the approved values. New UX decisions UX-31 to UX-34 cover how the approved rules are drawn; UX-17, UX-25 and UX-29 are revised. A new board, D07 Blind, interrupted and resume, was added.

**Second approval, 2026-10-03.** The user approved D16 to D18. D16 sets the daily intake limit at 120 minutes of new audio per learner per day; B01 originally showed minutes used today, a daily-limit-reached state and a clip-longer-than-what's-left state (UX-36); the latter is superseded by ADR 0033. D17 sets the sign-in lockout at 5 failed attempts, then a 15-minute pause; A01 now shows a one-try-left warning and the paused state with the time the learner can try again (UX-35), which closes the last placeholder tag. D18 accepts UX-31 (automatic Blind resume) as drawn.

## Artifacts

| Artifact | What it holds | Status |
| --- | --- | --- |
| [ListenUp UI (final, high fidelity)](https://claude.ai/artifact/SvknZCah3F9zuyBQyTNvov) | Every screen and state from the wireframes at 1280 and 360 px, light and dark, with an interaction spec beside each screen | Source of truth for build |
| [ListenUp design system](https://claude.ai/artifact/LsijobynKEzf1P5fvyYiRw) | Tokens (light and dark), type, spacing, motion, 19 components with guidelines | Updated in place (version 2) |
| [ListenUp wireframes](https://claude.ai/artifact/2VT1nLKWAz5aVpVYC951xp) | 36 low-fidelity boards with the original assumptions and open questions | Superseded for layout and copy; kept for history |

Where a wireframe and the final UI differ, the final UI and this log win. Requirement IDs refer to the [SRS](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd).

## Audit findings

The design system and wireframes are a strong base and were kept: rules shown as interface, absent (not greyed) forbidden controls, four-state AI feedback and the marks spine all hold up. The audit found 18 issues; 4 were blocking (two shortcut conflicts, two contrast failures). All are fixed in the final UI and design system.

| # | Area | Finding | Standard | Severity | Fix (decision) |
| --- | --- | --- | --- | --- | --- |
| F1 | Dictation keys | Ctrl+R (replay) reloads the page in every browser; Ctrl+Space switches the input language on macOS | Heuristic 5 (error prevention) | Blocking | New key map (UX-07) |
| F2 | Blind | A headphone or Bluetooth pause button, a call or a disconnect can pause Blind; nothing handled it | Heuristic 1, NFR-REL-3 | Blocking | Interruption handling (UX-17) |
| F3 | Tokens | `diff-wrong` light on `mark-bg` is 4.29:1 (a wrong word added to marks) | WCAG 1.4.3 | Blocking | #a84300, 4.72:1 (UX-20) |
| F4 | Toast | Success icon on the toast ground is 2.77:1 light and 1.66:1 dark | WCAG 1.4.11 | Blocking | Icons use the toast text colour (UX-20) |
| F5 | Tokens | `line-strong` dark on `accent-soft` is 2.83:1 (input borders in selected rows) | WCAG 1.4.11 | Major | #88908c, 3.76:1 |
| F6 | Step progress | Done and current bars differ by hue only (1.13:1 lightness gap) | WCAG 1.4.1 | Major | Done = soft fill + check, current = solid + "Now" (UX-09) |
| F7 | Step progress, mobile | Steps shortened to B D T C S: recall over recognition | Heuristic 6 | Major | Full name of current step + Plan sheet (UX-09) |
| F8 | Blind | Two Start controls (player and button) on one screen | One primary action; heuristic 4 | Major | One Start in the player slot (UX-08) |
| F9 | Buttons | Disabled Submit is skipped by Tab, so screen-reader users never hear why | WCAG 4.1.2, 3.3.1 | Major | aria-disabled with linked reason (UX-10) |
| F10 | Gist feedback | Missed key points shown before Dictation give away content, weakening "no guessing from context" | FR-DI-3 intent | Major | Hold details until Transcript when Dictation follows (UX-02) |
| F11 | Account deletion | Typing DELETE is a spelling task for B1 learners and adds no security | WCAG 3.3.8 spirit, heuristic 5 | Major | Re-authenticate plus one checkbox (UX-06) |
| F12 | Passage picker | A 10 s preview before Blind is a partial first listen | FR-BL-1 intent | Minor | Two 3 s boundary checks (UX-11) |
| F13 | Feedback colour | Decreases and missed points shown in `danger` red read as failure | FR-SH-15, goal 1 | Minor | Neutral ink with arrow and word (UX-12) |
| F14 | Effort | Results show scores only; effort is invisible | Goal 1 | Minor | Effort line on every result (UX-13) |
| F15 | Type and grid | Ad hoc sizes (19, 26 px) and 10, 18 px paddings; transcript words have a 30 px line | 8-point grid, modular scale | Minor | New scale and spacing (UX-14) |
| F16 | Touch | Mark chips are 32 px tall on touch | 44 px touch target | Minor | 44 px hit area (UX-15) |
| F17 | Sticky UI | Sticky header, player and toasts can cover the focused element on mobile | WCAG 2.4.11 | Minor | Scroll padding and toast placement (UX-16) |
| F18 | Baseline | Design system targeted WCAG 2.1 AA; breakpoints were 360/720/1080 | Agent standard: WCAG 2.2 AA, 360/768/1280 | Minor | README and tokens updated |

## Decisions

UX-01 to UX-06 settle the open UX questions from the wireframes. The rest come from the audit and the experience goals.

| ID | Decision | Why | Alternatives considered | Serves |
| --- | --- | --- | --- | --- |
| UX-01 | Levels use one hue (`accent`), four pips and the word (Needs work, Fair, Good, Excellent). Never red to green. | Feedback is guidance, not a verdict; works for colour-blind learners; the word carries the meaning. | Red-to-green scale (reads as pass/fail, shames); traffic-light badges | FR-BL-7, FR-SH-9, FR-SH-15, NFR-USE-2 |
| UX-02 | Gist key points: when Dictation comes next, Blind feedback shows score, level, rubric parts and "You captured 2 of 4 key points"; the written feedback and the key-point list wait in Transcript. With Blind only, everything shows at once. | Missed points tell the learner what the passage says, which lets them guess words in Dictation. Transcript is where FR-BL-10 shows them anyway. | Show everything now (wireframe); hide everything until Transcript (loses motivation) | FR-BL-7, FR-BL-8, FR-BL-10, FR-DI-3, BL-4 |
| UX-03 | Shadow rounds 2 and 3 may show one tip, with strict limits: only the learner's own marked phrase (4 words at most) plus a sound instruction; static, never synced to the audio; shown before the round and pinned as one line during it. The tip generator must reject any tip quoting words outside a mark; then no tip shows. | The learner already saw their marks in Transcript; a phrase plus a sound cue is coaching, not the transcript. Syncing it to audio would turn it into karaoke. | Remove tips (loses the most useful feedback loop); show the round 1 transcript lines with marks (breaks FR-SH-2) | FR-SH-2, FR-SH-11, FR-SH-14 |
| UX-04 | Late results: if the learner is on the screen that owns the result, it fills in place with no toast and a polite announcement. If they moved on, a toast with "View" (8 s, pauses on hover and focus, never takes focus) plus a "New" badge on the step, the plan overview and the library row. Several results merge into one toast. | Waiting never feels stuck, and nothing jumps under the learner's cursor. The badge keeps the result findable after the toast goes. | Toast always (noisy while on the screen); in place only (missed after moving on) | FR-BL-11, FR-SH-16, FR-CI-5, NFR-AI-8 |
| UX-05 | Export lives in Settings as an inline status card: choose "My data" (JSON and CSV, always) and "My files" (uploads and recordings, ZIP, optional); states Idle, Preparing, Ready (download in the app and by email, link valid 7 days), Expired, Failed with retry. | Status is visible where it was requested; email covers long jobs; splitting files keeps the common case small. | Email only (no status in app); one big ZIP (slow, large) | NFR-SEC-5, DR-1 |
| UX-06 | Account deletion is its own two-step page: (1) what goes, with counts, and an export offer; (2) re-enter the password (or re-confirm with Google) and tick "I understand this can't be undone", then "Delete my account". | A full page gives room to list consequences; re-authentication is real security; a checkbox is easier than typing a word for B1 learners. | Small dialog with typed DELETE (wireframe) | FR-ACC-4, DR-1, NFR-SEC-4 |
| UX-07 | Keys. Outside text fields: Space or K play/pause, J back 5 s, R replay segment or line, \[ and \] speed, ? keys list. Inside the Dictation box: Esc play/pause, Ctrl+Alt+J back 5 s, Ctrl+Alt+R replay, Ctrl+Alt+\[ and \] speed (Ctrl+Option on Mac). Blind: no keys act on playback. | The wireframe keys reloaded the page (Ctrl+R) or switched language (Ctrl+Space). Esc is free in a text box; Ctrl+Alt is not used by browsers. | Ctrl+Space and Ctrl+R (conflicts); F-keys (need Fn on laptops) | FR-DI-2, FR-TR-1, UI-4 |
| UX-08 | Blind has one Start control: the player's main slot becomes a labelled "Start listening" button. No second button. | One primary action; the learner looks to the player for playback. | Two Start controls (wireframe) | FR-BL-1, UI-1, UI-3 |
| UX-09 | Step progress: done = soft fill and check, current = solid accent and "Now", locked = sunken and lock, skipped = struck name and "Skipped". At 360 px show "Step 2 of 5 · Dictation" with the bar and a Plan button that opens a sheet with the full list. | No information by hue alone; no cryptic letters on mobile. | Letter abbreviations (wireframe); scrolling labels | FR-PL-3, FR-PL-4, FR-PL-7, UI-4 |
| UX-10 | An action waiting for a condition is aria-disabled, stays focusable, and has its reason as visible helper text linked by aria-describedby; activating it moves focus to the reason. | Keyboard and screen-reader users learn why it is not available. | Native disabled (skipped by Tab) | FR-BL-4, NFR-USE-3 |
| UX-11 | Passage picker before Blind offers "Hear start" and "Hear end": 3 s around each boundary only. | Checks the cut points with the least exposure before the one listen. | 10 s preview (wireframe); no preview | FR-CI-4, FR-BL-1 |
| UX-12 | Red (`danger`) is only for errors and destructive actions. Lower scores show in ink with a down arrow and the word "lower"; missed key points use a hollow circle and "Missed". | Hard practice must feel safe; a drop between rounds is normal. | Red for drops and misses (wireframe) | FR-SH-15, FR-BL-10 |
| UX-13 | Every result shows an effort line: replays, minutes listened, marks found, rounds recorded. | Celebrate effort, not only scores. | Scores only | FR-DI-2, FR-SH-5 |
| UX-14 | Type: display 40/48, title 28/36 (24/32 mobile), heading 20/28, body-l 18/32, body 16/24, body-s 14/20, label 13/16. Spacing on a 4/8 grid. Breakpoints 360, 768, 1280. Practice layout max 1120 px: work area plus a 320 px side panel; reading text at most 68 characters a line. | A 1.2 heading scale; a 32 px transcript line gives every word a 32 px tall target. | Keep the old ad hoc sizes | UI-4, NFR-USE-2 |
| UX-15 | Targets: 44 px on touch layouts (chips keep a 32 px look with a 44 px hit area), 24 px minimum on desktop. Words in the transcript use the inline-target exception plus the 32 px line. | WCAG 2.5.8 and thumb use. | 32 px chips | UI-4 |
| UX-16 | Sticky header and player set `scroll-padding-top` to their height; toasts sit above the bottom action bar and move up when the keyboard opens; nothing sticky covers focus. | WCAG 2.4.11 Focus not obscured. | None | UI-4, NFR-USE-2 |
| UX-17 | Blind interruptions (revised 2026-10-03 for D13). The first interruption the learner did not cause (network stall, or a device or OS pause under 5 s) pauses and then resumes once, from 3 s before the stop (UX-31, board D07). During an unfinished listen, a second interruption, a device pause of 5 s or more, leaving, reloading or seeking ends the attempt; in-app navigation including Back warns first, and leaving or reloading after listen completion preserves it (ADR 0033); the dialog names the cause. After two ended attempts, a calm line offers "Switch to Dictation" while the entry can still change. | Matches SR-5 without blaming the learner; gives a way out of a loop. | Silent restart; any interruption ends the attempt (the rule before D13) | FR-BL-3, SR-5, NFR-REL-3, FR-PL-5 |
| UX-18 | Dialogs become bottom sheets below 768 px; the safe action is first on mobile (top) and right-most on desktop; Escape and the scrim pick the safe action. | Thumb reach and error prevention. | Centred dialogs on mobile | FR-BL-3, FR-PL-7 |
| UX-19 | Navigation: library screens show Library, Settings and the account menu; practice screens swap them for "Plan" and the save status; Blind playback hides Plan entirely. | Fewer ways to leave by accident; focus on listening. | Full nav everywhere | UI-1, FR-BL-3 |
| UX-20 | Colour fixes: `diff-wrong` light #a84300; `line-strong` dark #88908c; new `accent-hover`, `focus-ring`, `toast-bg`, `toast-ink`; toast icons use the toast text colour. | Findings F3 to F5. | None | NFR-USE-2 |
| UX-21 | Deleting a clip shows exactly what goes for this learner: sessions, marks, cards, recordings and transcript corrections. It does not mention the shared transcript. | DR-2 is settled; the learner only needs to know their own data goes. | Generic "Are you sure?" | FR-CI-7, DR-2 |
| UX-22 | Live regions: one polite region per screen for results and counters (counters debounced 1 s); assertive only for a voided Blind attempt and a failed recording. Pending panels set aria-busy. | Screen-reader users hear results once, without noise. | Announce everything | NFR-USE-2 |
| UX-23 | Motion: 120 ms hover and focus, 200 ms panels and state swaps, 320 ms dialogs and sheets; easing cubic-bezier(0.2, 0, 0, 1). Nothing moves near the player while audio plays; skeletons do not shimmer; all motion off under reduced motion. | Focus on listening; reduced motion respected. | Shimmer skeletons; auto-scroll during Blind | NFR-USE-2 |
| UX-24 | Results that arrive in parts reserve their final size: score row, measure rows and text block keep fixed heights from pending to ready. | No layout jumps (goal 3). | Grow as content arrives | FR-SH-9, FR-SH-11 |
| UX-25 | Product placeholders were drawn as dashed warning tags with the question code, for example `[MAX SIZE · OI-4]`, so nobody ships a guessed value. Resolved 2026-10-03: every tag tied to D1 to D15 now shows the approved value, and spec panels cite the decision (for example D5). The last tag, `[LOCKOUT TIME]` on A01, was closed by D17 (2026-10-03); no placeholder tags remain. | Makes open decisions visible on every screen they touch. | Invented values | OI-4, OI-5, OQ-6, D1 to D15, D17 |

Decisions made while drawing the final screens:

| ID | Decision | Why | Alternatives considered | Serves |
| --- | --- | --- | --- | --- |
| UX-26 | On a learner's first plan, Blind is pre-ticked and tagged "Recommended to start"; later plans remember the last choice. | Fewer decisions at the start (goal 6); Blind is the shortest entry (about 3 min). | Nothing pre-ticked; both pre-ticked (about 45 min) | FR-PL-1, NFR-USE-1 |
| UX-27 | Dictation submit asks once ("Submit your Dictation? You typed 63 words") because the text can't change afterwards. | Error prevention for an irreversible action. | Submit with no check | FR-DI-4, FR-DI-5 |
| UX-28 | Learner-facing copy says an attempt "ends", never "void". | Plain B1 English; "void" reads as a penalty. | "Void" (wireframe) | FR-BL-3, SR-5 |
| UX-29 | Every passage is 30 s to 15 min on every path, confirmed by product on 2026-10-03 (D2, D15). The picker clamps typed times at both limits and disables "Whole clip" with its reason when the clip is longer than 15 min. | A shorter passage gives too little for Dictation and Shadow. | No minimum | FR-CI-4, D2, D15 |
| UX-30 | Theme follows the system by default, with Light and Dark in Settings. | Respects user preference; both themes are fully specified. | Light only | NFR-USE-2 |
| UX-31 | Blind resume (D13) is automatic: on a stall the player freezes and says "Waiting for connection" with "Resume 1 of 1"; when audio is buffered again a 3 s count runs and playback goes on from 3 s before the stop. "Carry on now" only shortens the count; there is no control to stay paused. After the resume, the rule line says the resume is used. A second interruption opens the "attempt ended" dialog naming when the resume was used. Status: accepted by the user (D18, 2026-10-03). | Keeps the one unbroken listen honest: a resume the learner starts at will would work as a pause. The 3 s lead-in rebuilds context without a real rewind. | Resume button with no time limit (works as a pause); restart from the exact stop (loses the sentence) | FR-BL-3, SR-5, NFR-REL-3, D13, D18 |
| UX-32 | Feature-flag variants are drawn beside the MVP default, never instead of it: the main frames show upload only (D10) and flagged states carry a boxed accent tag "Flag on · youtube\_intake". With the flag on, YouTube stays a secondary action. | Developers build the default first and can see exactly what the flag adds. | Draw both routes as equals; leave YouTube out of the canvas | FR-CI-1, FR-CI-2, OQ-6, D10 |
| UX-33 | Accent (D11) moves out of the measures list into its own "Accent guidance" block with the words "Not in your score" and "compared with this speaker"; the comparison table gives it its own row group. The overall score is the average of the six scored measures (D3). | A number among scored measures reads as a verdict; a separate, labelled block makes the exclusion visible in words, not colour. | Keep accent in the list with a footnote; hide accent entirely | FR-SH-4, FR-SH-9, FR-SH-15, D3, D11 |
| UX-34 | Account deletion with a 7-day grace (D9): step 1 states the date the account is deleted for good; step 2's checkbox repeats it; after step 2 the account is "switched off" (not "locked"); signing in within 7 days opens "Restore your account?" with Restore as the primary action and "Keep it deleted" (signs out). | The grace period only helps if the learner knows the date and how to undo; an explicit restore step prevents an accidental restore by a shared device. | Silent restore on sign-in; immediate deletion | FR-ACC-4, DR-1, NFR-SEC-4, D9 |
| UX-35 | Sign-in lockout (D17): the 4th failed try shows a calm warning, "One try left", with the reset link. The 5th opens a paused state that gives the clock time ("Sign-in is paused until 10:57 AM") and the minutes left, with Reset password as the next action; Sign in stays focusable with aria-disabled and points to the time. The same words show whether or not the email has an account. Assumption, to confirm in the security review: a completed password reset ends the pause and Continue with Google is not paused. | A clock time is a number the learner can act on; warning one try early prevents the lock (error prevention). Identical messages keep the lock from revealing accounts. The minute countdown updates silently so screen readers are not flooded. | "Too many tries, wait a while" with no time; a live seconds countdown; a CAPTCHA instead of a pause | FR-ACC-2, NFR-SEC-1, NFR-USE-3, D17 |
| UX-36 | Daily intake limit (D16): B01 shows "13 min of 120 min of new audio added today" under the storage meter. The server checks admission before upload and again on confirmation: each playable clip counts at most 15 minutes, pending clips reserve 15 minutes each, and a clip admitted below the allowance is accepted whole even if it crosses it. Browser duration is not an admission check; at the limit, a caution (not an error) says when adding opens again and points to the library, and "Choose a file" is aria-disabled with that reason. Practice is never limited. The day resets at midnight UTC; show the server's reset time in the learner's local time. Supersedes the remaining-minutes refusal and local-midnight assumption ([ADR 0033](../adr/0033-design-review-policy-resolutions.md); ADR 0027). | Showing usage before the learner chooses a file prevents a wasted upload. The limit is a rule, not a mistake, so it uses the neutral caution style and points to what the learner can do now. | Refuse only after upload; an error-red banner; hide the limit until it is reached | FR-CI-1, FR-CI-3, NFR-USE-3, D16 |

## Interaction spec (shared rules)

Each screen on the UI canvas has its own spec panel (states, focus order, keys, announcements). These rules apply everywhere.

**Keyboard map (UX-07)**

| Action | Outside text fields | Inside the Dictation box | Blind |
| --- | --- | --- | --- |
| Play / pause | Space or K | Esc | Start only, once |
| Back 5 s | J | Ctrl+Alt+J | None |
| Replay segment or line | R | Ctrl+Alt+R | None |
| Slower / faster | \[ and \] | Ctrl+Alt+\[ and \] | None |
| Keys list | ? | None (button only) | ? |
| Mark word (Transcript) | Enter on a focused word; Shift+Arrow extends | n/a | n/a |
| Mark list row | Enter seeks, E edits, Delete removes (Undo in toast) | n/a | n/a |

Mac uses Ctrl+Option in place of Ctrl+Alt. Shortcuts act only on keydown, call preventDefault, and never fire while a dialog or sheet is open. The "Keys" button in every practice header lists the keys for the current mode.

**Focus order on practice screens:** skip link → header (Plan, save status, Keys) → step progress (Change entry) → player → rule line → work area → side panel → primary action → secondary actions. On arrival at a step, focus goes to the step heading (h1). Dialogs focus their safe action; on close focus returns to the trigger.

**States every async result has:** pending (spinner, honest estimate, aria-busy), partial (arrived parts shown, the rest held in fixed-height skeletons), ready, unavailable (what is saved, Retry, next automatic try, the next step still available), late (UX-04).

**Estimates shown:** gist "usually under 10 seconds", Shadow round "usually under a minute", comparison "usually under 30 seconds", transcript "about N min" from live estimates. Copy always says "usually" or "about", never a promise.

**Motion tokens:** `duration-fast` 120 ms, `duration-base` 200 ms, `duration-slow` 320 ms; easing `cubic-bezier(0.2, 0, 0, 1)` in, `cubic-bezier(0.3, 0, 1, 1)` out. Toast enters from 8 px below with fade; sheet slides up 320 ms; nothing animates under prefers-reduced-motion except the recording dot, which stops pulsing but stays visible.

**Announcements (polite unless noted):** "Gist feedback ready: 78, Good." · "Round 2 saved." · "Round 2 scores ready: 76, Good. Written feedback is coming." · "2 of 3 sentences. Write one more." · "Mark added: a lot of, 01:12." · assertive: "Blind attempt ended because playback stopped." · assertive: "Round 2 could not be saved. Your take is kept on this device. Try again."

## Proposals to change product rules

All four proposals were accepted by the user on 2026-10-03 (decisions D11 to D14) and are now designed in.

| ID | Rule today | Problem for the learner | Proposal | Status (2026-10-03) |
| --- | --- | --- | --- | --- |
| P-1 | SR-6: a session completes when Shadow's three rounds are done, or when Card and Shadow are both skipped. | A learner who makes cards and then skips Shadow (for example, no microphone) is left with a session that never completes. | Complete the session when Shadow is done or skipped, whatever happened in Card. The UI already treats it so (G04, I01). | Accepted as D12. Drawn in C02, G04, H07 and I01: the session completes when Shadow is done or skipped. |
| P-2 | SR-5, NFR-REL-3: any interruption voids Blind. | A network stall or a Bluetooth glitch that the learner did not cause restarts the whole passage; repeated voids push learners to quit. | Allow one resume per attempt after an interruption the learner did not cause (network stall, device pause under 5 s), from 3 s before the stop. Leaving or reloading still voids. | Accepted as D13 (one resume after a network stall or a device pause under 5 s; a second interruption ends the attempt). New board D07; D01, D02 and D03 updated (UX-31). The automatic resume in UX-31 was accepted by the user as D18 (2026-10-03). |
| P-3 | FR-SH-4, FR-SH-9: accent is graded and counts in the overall round score. | A number for accent reads as a verdict on the learner, against FR-SH-15. | Keep the accent measure as guidance named "Accent match (this speaker)" and leave it out of the overall score. | Accepted as D11. Accent guidance block, "Not in your score", in H05, H06 and H08; overall = average of six measures (UX-33). |
| P-4 | FR-CA-1: at most two cards per session. | The rule says nothing about deleting; learners will want to swap a card. | Confirm that deleting a card frees its slot within the session (the UI assumes yes; the server still rejects a third live card). | Accepted as D14. Delete-card dialog and "1 left" state in G02; G01 and G03 updated. |

## Product questions (all decided 2026-10-03)

These were product decisions, not UX ones. All were decided by the user on 2026-10-03 (D1 to D15) and every dashed placeholder tag (UX-25) now shows the approved value. The sign-in lockout time and the daily intake limit, the last two open values, were decided in the second approval on 2026-10-03 (D17, D16), so no question in this section is open.

| Question | Placeholder in the UI | Screens | Recommendation | Decision (2026-10-03) |
| --- | --- | --- | --- | --- |
| Maximum upload size and storage per account (OI-4) | \[MAX SIZE · OI-4\], \[STORAGE LIMIT · OI-4\] | A03, B01, I02 | 500 MB per file, 2 GB per account; show use against the limit in Settings. | Decided (D5): 500 MB per file, 2 GB stored uploads per account. Shown in A03, B01 (limit and storage meter), I02. |
| Google sign-in in the MVP (OI-5) | \[GOOGLE SIGN-IN · OI-5\] tag on the button | A01, A02, I02, deletion step 2 | Yes: it removes a password step for most learners. | Decided (D6): Google sign-in in the MVP. Button shown without a tag in A01, A02 and I02. |
| Recording retention | \[RETENTION · 90 DAYS?\] | H02, I02 | 90 days, then automatic deletion, stated in the consent. | Decided (D7): recordings kept 90 days, then deleted; grades and word labels stay. H02, I02. |
| Grading timeout before "Feedback unavailable" (FR-BL-11) | \[TIMEOUT\] in the spec panels | D06, H07 | Gist 30 s, Shadow round 120 s, comparison 90 s (about 3× the p95 targets). | Decided (D3): gist 30 s, Shadow round 120 s, three-round comparison 90 s. D06, H07, H08 spec panels. |
| Rubric weights (gist) and Shadow overall-score weights | \[WEIGHTS · TO CONFIRM\] beside "Score by part" | D05, H05, H06, H08 | Gist 50/30/20 as drafted; Shadow equal weights, accent excluded (P-3). | Decided (D3, D11): gist 50/30/20; Shadow overall = equal weights of six measures, accent excluded. Consistency threshold 10 points. D05, H05, H06, H08. Revisit after the golden sets are scored. |
| Card review and score trends in the MVP (FR-CA-5, FR-BL-15, FR-SH-19) | \[MVP? · FR-CA-5\] on Library tabs; trend slot labelled | A04, G03, I01 | Ship card review (small, high value); defer trends to v1.1. | Decided (D1): card review ships in the MVP; score trends (FR-BL-15, FR-SH-19) move to v1.1 and are removed from A04 and I01. |
| Shadow when the passage is shorter than 60 s | \[SHORT PASSAGE RULE\] banner variant | H01 | Use the whole passage when it is 30 s or more; under 30 s, ask the learner to extend the passage before Shadow. | Decided (D8, D2): Shadow uses the whole passage when the passage is 30 to 60 s; passages are never under 30 s. H01, C01, C02. |
| Immediate vs grace-period account deletion | \[IMMEDIATE OR 7-DAY GRACE\] in step 2 copy | I02 deletion | 7-day grace: the account is switched off at once and deleted after 7 days; sign-in offers explicit restoration. | Decided (D9): 7-day grace; the account is switched off at once; signing in within 7 days offers Restore or Keep it deleted, and only Restore reactivates it (ADR 0033). I02 deletion flow and restore states (UX-34). |
| YouTube availability pending legal review (OQ-6, OI-1) | \[OQ-6\] tag on the YouTube tab; upload-only variant drawn | A03, B02, B03 | Build the upload-only variant first so launch does not wait on legal review. | Decided (D10): upload-only path is the MVP default; YouTube intake behind the youtube\_intake flag until legal review. A03, B01, B02, B03 (UX-32). |
| Export of media fetched from YouTube | \[OQ-6\] note in the export card | I02 | Exclude it; export uploads and recordings only. | Decided (D10): YouTube media is excluded from export. I02, B02. |
| Sign-in lockout time (security) | \[LOCKOUT TIME\] in the "Too many tries" state | A01 | A security value, outside D1 to D15; whatever the value, show when the learner can try again. | Closed (D17): after 5 failed attempts, sign-in for that account is paused for 15 minutes (configurable); per-IP rate limits stay. A01 shows the one-try-left warning and the paused state with the clock time and minutes left (UX-35). |
| Daily intake limit (issue #41) | None (no limit was drawn) | B01, B02 | 120 minutes of new audio per learner per day. | Decided (D16): 120 minutes of new audio per learner per day (configurable). B01 must show counted minutes and pending reservations, the limit-reached state and the UTC reset formatted locally; B02 reuses them. The remaining-minutes refusal state is superseded (UX-36, ADR 0033). |

## Screens and states covered

The inventory below records the required states after [ADR 0033](../adr/0033-design-review-policy-resolutions.md). The published UI canvas has not been updated by this documentation PR; its intake and Blind navigation/media states need a separate visual revision.

All 36 wireframe boards have a final board on the [UI canvas](https://claude.ai/artifact/SvknZCah3F9zuyBQyTNvov), each at 1280 and 360 px in light and dark, with an Other states column and a spec panel. On 2026-10-03 one board was added (D07 Blind, interrupted and resume), so the canvas holds 37 screen boards.

| Area | Boards | Extra states drawn |
| --- | --- | --- |
| Account and library | A01 to A04 | Wrong password, reset sent, one try left, locked for 15 minutes with the retry time (D17), signing in, short password, email taken, terms not ticked, empty Marks and Cards tabs, upload-only MVP default with the YouTube flag-on variant, card review panel, row menu, delete clip, late "New" badge |
| Add clip | B01 to B04 | Drag over, wrong type, too large (500 MB), connection lost, storage meter and storage full (2 GB), minutes of new audio used today, daily limit reached (120 min, D16), pending 15-minute reservations and UTC reset displayed locally (supersedes the remaining-minutes refusal), YouTube flag-on switch, private, age-restricted, not a link, Shorts, flag switched off, downloading (flag), ready, download failed (flag), transcript failed, ready toast, typed over 15 min clamped, whole clip over 15 min disabled, under 30 s, clamped time, focused handle |
| Plan | C01, C02 | Nothing ticked, 4-step plan, Dictation unavailable, transcript not ready, change entry panel, entry locked, skipped row |
| Blind | D01 to D07 | Test sound, after 2 attempts, keys popover, network stall (kept, resuming), listen complete, leave sheet including Browser Back, whole-clip playback unavailable during an unfinished listen, completed listen preserved on gist-form leave/reload, attempt ended (left, device pause of 5 s or more, second interruption), switch to Dictation, waiting for connection, back online count, resume used, device pause under 5 s, still offline, gist ready/early/offline/long/submitting, Blind-only feedback, pending, unavailable, retries used, late toast |
| Dictation | E01 to E03 | Submit check, empty, offline, pre-transcript segments, waiting, transcription failed, ready toast, word actions sheet, dispute editor, re-score, added toast |
| Transcript | F01, F02 | Mark editor (popover and sheet), no marks, unconfirmed marks, back to current line, gist pending, row editing, empty list, Undo toast |
| Card | G01 to G04 | Heard form missing, saved, delete card, delete frees a slot ("1 left"), limit, replace which card, server refusal, review hidden and revealed, card deleted from review, end of deck, skip Card, skip Shadow, no microphone |
| Shadow | H01 to H08 | Below 60 s, over 90 s, whole passage when 30 to 60 s, consent with 90-day retention, mic blocked, too quiet, leak, no mic, count-in, saved, save failed, between rounds with tip, no tip, pending, partial, accent guidance block, written feedback failed, ready, word compare, drop shown neutral, unavailable, late toast, comparison writing and unavailable |
| Finish and settings | I01, I02 | Pending tile, skipped tiles, cards made with Shadow skipped (still complete), export preparing, ready, expired, deletion steps 1 and 2 with the 7-day date, switched off, explicit restore confirmation on sign-in, keep it deleted, restored, deleted after 7 days |

## Self-review (WCAG 2.2 AA and the 10 heuristics)

Every board was checked before hand-off; what failed was fixed in the boards and the design system.

| Check | Result |
| --- | --- |
| 1.4.3 / 1.4.11 contrast, both themes | Pass after UX-20 (all text 4.5:1 or more, controls and icons 3:1 or more) |
| 1.4.1 use of colour | Pass: steps, levels, diff, word labels, deltas and statuses all carry an icon, line style or word |
| 2.1.1 keyboard, 2.1.4 shortcuts | Pass: every control is a real button, link or input; shortcuts only on keydown with focus rules (UX-07) |
| 2.4.3 focus order, 2.4.7 visible focus | Pass: order listed per board; 3 px ring |
| 2.4.11 focus not obscured | Pass with UX-16 scroll padding and toast placement |
| 2.5.7 dragging, 2.5.8 target size | Pass: typed time fields beside every handle; 44 px touch targets, 24 px desktop minimum |
| 3.3.1 / 3.3.3 errors | Pass: every error names what happened and what to do |
| 3.3.8 accessible authentication | Pass: paste allowed; deletion uses re-auth and a checkbox |
| 4.1.3 status messages | Pass: live-region policy UX-22 |
| 2.3.3 / reduced motion | Pass: no motion under reduced motion; nothing moves near the player |
| Heuristics 1 (status) and 5 (error prevention) | Pass: five-state async results, honest estimates, safe defaults in every dialog |
| Heuristics 4 (consistency) and 6 (recognition) | Pass after UX-09 (no letter abbreviations) and UX-08 (one Start) |
| Heuristic 9 (recover from errors) | Pass: Undo on marks, retry on every AI result, clear next actions |
| Re-check of changed boards, 2026-10-03 (A01 to A04, B01 to B04, C01, C02, D01 to D07, G01 to G04, H01, H02, H05 to H08, I01, I02) | Pass. New parts use existing tokens: text 4.5:1 or more in both themes (muted on sunken 5.62:1 light, 8.01:1 dark; warning on sunken 4.99:1 light); flag tag 7.7:1 light, 7.85:1 dark. Status changes use role=status (polite); only a second Blind interruption is assertive. Accent exclusion is stated in words. Aria-disabled "Whole clip" keeps its reason linked. The countdown has no motion and a button to skip it (2.2.1 not affected: the learner never needs more time). Heuristics 1, 5 and 9 hold for the resume, grace period and clamped passage. |

Known limits: the boards are static mock-ups and were not rendered in a browser during this review; contrast was computed from the token values. A build-time axe and screen-reader pass is still needed.
