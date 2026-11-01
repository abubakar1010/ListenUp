# #98 manual screen-reader checklist

For the owner. **Not run.** Nothing here has been checked with a screen reader yet, and
the accessibility statement says so. Record the results in the tables, with the date,
the versions and the build, and keep this file as the evidence for #98.

Use one desktop and one mobile pairing (the issue asks for one of each):

| Pairing | Reader | Browser | Device | Why this one |
| --- | --- | --- | --- | --- |
| Desktop | NVDA (current release) | Firefox, then a quick repeat in Chrome | Windows 11 | The most used free desktop reader |
| Mobile | VoiceOver | Safari | iPhone with the current iOS | The most used mobile reader; WebKit is also the engine with the most recording differences (#99) |

TalkBack with Chrome on Android, or VoiceOver on macOS, can replace one of these if the
device is not available; note the substitution.

## Before you start

- Run the stack locally (`docker compose up --build`) with the fake AI configuration, or
  use a staging build. Seed a learner and a clip (`uv run python scripts/seed_dev.py`), or
  upload a clip of 30 to 60 seconds so Shadow uses the whole passage.
- Turn the reader's speech viewer or caption panel on (NVDA: Tools → Speech viewer;
  VoiceOver: Accessibility → VoiceOver → Caption panel), so what was announced can be
  copied into the tables.
- Desktop: use the keyboard only. Mobile: use swipe and double-tap only, with the
  on-screen keyboard for typing.
- For each row, write **Pass**, **Fail** (with what was heard) or **Not possible** (why).

## 1. Entry and navigation

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 1.1 | Load `/sign-in`, sign in | The skip link is the first stop; fields are announced with their labels; a wrong password is announced as an alert, including the lockout time when it applies | | |
| 1.2 | Library | The page title is announced; the h1 and the section headings for plans and clips are in the headings list; each clip says its status | | |
| 1.3 | A clip becomes ready while the library is open | "… is ready" is announced politely and focus does not move | | |
| 1.4 | Open `/accessibility` | It reads as a page with an h1 and section headings; the draft note is read | | |

## 2. Start a plan (all three paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 2.1 | Whole clip / part of it | Radios announce their names and state; the passage handles announce as sliders and read their value as a spoken time, not digits | | |
| 2.2 | Blind and Dictation checkboxes | Each announces its name, its description and checked state; "Your plan: 4 steps" or "5 steps" is announced when it changes | | |
| 2.3 | Start plan | Focus moves into the session; "Step 1 of N" is read | | |
| 2.4 | At 360 px or on the phone, Plan button | The sheet opens as a dialog named "Your plan"; Escape or the close control returns focus to Plan | | |

## 3. Blind (Blind and both paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 3.1 | Before you start | The rules list is read; the only controls are Start listening and Volume | | |
| 3.2 | Start listening | Focus moves to the listening status; no pause, seek or speed control exists; the reader's own media keys do not pause | | |
| 3.3 | Leave mid-listen (Back) | "Leave Blind?" opens as a dialog with focus on Stay | | |
| 3.4 | Interrupt (turn the network off for 2 s) | The "Connection lost at …" status is announced; "Ready to carry on … in 3" takes focus with Carry on now | | |
| 3.5 | Void (reload mid-listen) | "Your Blind attempt ended" is announced assertively with the reason | | |
| 3.6 | Gist form after the listen | Focus is in "Your gist"; "2 of 3 sentences. Write one more." is read politely while typing | | |
| 3.7 | Submit gist | Focus moves to "Your gist feedback"; "Preparing your gist feedback…" is read; Continue is the next stop | | |
| 3.8 | Grade arrives (or after 60 s, unavailable) | "Your gist feedback is ready." or "Feedback unavailable" is announced without moving focus; Retry feedback is reachable | | |

## 4. Dictation (Dictation and both paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 4.1 | Arrival | Focus is in "Your text" (UX-42); its help (word count, spell check off) is read | | |
| 4.2 | Player keys inside the box | Esc plays and pauses; Ctrl+Alt+J goes back 5 s; the keys are listed on the page | | |
| 4.3 | Draft saving | "Draft saved" changes are not read on every keystroke; a save problem is announced | | |
| 4.4 | Submit for scoring | The dialog opens on Keep typing; Submit moves the plan on; focus goes to the Transcript heading | | |
| 4.5 | Score arrives while waiting | "Your Dictation is scored: N%." is announced | | |
| 4.6 | Add a missed word to the marks | "Added “word” to your marks." is announced; the button then reads "“word” added to marks" | | |

## 5. Transcript and marks (all paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 5.1 | Arrival | Focus is on the h1 "Transcript: …"; "Entry locked" is read in the progress | | |
| 5.2 | Words | Each word is a button "Jump to …"; an edited word says "edited"; marked words are described as "Marked" | | |
| 5.3 | Mark by keyboard (desktop) | Arrows move, Shift+arrow selects, M marks; "N marks." and the save status are announced | | |
| 5.4 | Mark on the phone | A word can be chosen and marked with the on-screen controls alone | | |
| 5.5 | Marks list | Play mark, Edit note, Remove and Confirm (for marks from Dictation) are named with the phrase; Undo is reachable after Remove | | |
| 5.6 | Finish Transcript with a save pending | Finish stays focusable, says why it waits, and moves focus to the reason | | |
| 5.7 | Gist feedback panel (Blind paths) | The grade, if it arrives here, is announced politely | | |

## 6. Card (all paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 6.1 | Arrival | Focus is on "Keep a sound you missed"; "2 left" is read | | |
| 6.2 | Marked phrase | The marks made in Transcript are offered (fixed in #98); the written form fills in | | |
| 6.3 | Save card | "1 left" is announced; the card's Play audio and Delete card are named with the phrase | | |
| 6.4 | Third card | Save card is aria-disabled and says why | | |
| 6.5 | Skip Card | The dialog opens on Make a card; Skip Card moves the plan on and focus is not lost | | |

## 7. Shadow (all paths)

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 7.1 | Arrival | Focus is on the h1 "Shadow: …"; the segment is described | | |
| 7.2 | Check microphone | "Microphone ready. Sound detected." is announced; a refusal explains how to allow it | | |
| 7.3 | Voice consent | The checkbox and "Agree to voice recording" are reachable; after agreeing, focus is on the confirmation | | |
| 7.4 | Start round 1 | Focus moves to "Round 1 of 3"; the transcript text is readable in round 1 only | | |
| 7.5 | Play round N | "Round N starts in 3" counts down and "playing at original speed" is read, once each | | |
| 7.6 | Round ends | "Recording saved for round N." is announced. **Known issue:** focus moves to the top of the page (reported, see 98-keyboard-and-statement.md); note what the reader does | | |
| 7.7 | Third round | The plan finishes: "All N steps finished" is read; "Feedback unavailable" for each round is readable with its retry | | |
| 7.8 | Replays on the finished plan | "Your recording of round N" and "Original, round N segment" players are named; native controls are usable | | |

## 8. Saved cards and marks

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 8.1 | `/cards` review | The written form stays hidden until revealed; Heard, Unsure and Missed are named; "Saved: …" is announced | | |
| 8.2 | `/marks` | Marks are listed newest first, each with a link to its source time | | |

## 9. Settings and the statement

| # | Check | Expected | Desktop | Mobile |
| --- | --- | --- | --- | --- |
| 9.1 | Settings | Export, consents and deletion sections have headings; the Accessibility statement link is named | | |
| 9.2 | Export | "Preparing…" and "Ready" states are announced | | |

## Result

| Pairing | Date | Versions (reader, browser, OS) | Build | Passed | Failed | Not possible | Tester |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Desktop | | | | | | | |
| Mobile | | | | | | | |

File each failure as a GitHub issue that names the row, and link it here. Update the
"Where we are" and "Known limitations" sections of the accessibility statement from
the result.
