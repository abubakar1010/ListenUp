Source: https://claude.ai/code/artifact/5d73e467-e587-4d4f-946d-a9fd2c0ab5f6 · Exported 2026-10-09

# Product Requirements Document: English Listening Practice App

Oct 2, 2026 · @Md. Ebrahim Hossen

## 1. Overview

This app turns any video or audio clip into a structured English listening workout, guiding the learner through five exercises: Dictation, Blind, Transcript, Card and Shadow.

**Problem.** Most learners "practice listening" by passively watching content with subtitles. That hides the real gap: they cannot decode connected speech ("could have" heard as /kʊdəv/, "a lot of" as /əlɒtə/). Context lets them bluff, so they feel they understand while the same sounds fail again and again.

**Solution.** The learner brings their own content (an uploaded file or a YouTube link). The app enforces a proven listening plan that first measures what they cannot hear, then fixes it. Each mode has strict rules (for example, Blind forbids pausing) because the discomfort is the training.

**Product principles**

- Diagnostic over comfortable: the app exposes decoding failures instead of hiding them.
- Rules are the feature: constraints such as no pause and no rewind are enforced, not suggested.
- Own content: the learner chooses material they care about.
- Small output: at most two cards and one 60 to 90 second shadow segment. Depth over volume.

## 2. Goals, non-goals and success metrics

The product succeeds if learners finish the full plan on real content and the same decoding failures shrink over time.

**Goals**

- G1: Let a learner start a plan from an uploaded file or a YouTube link in under one minute.
- G2: Enforce each mode's rules exactly (no pause in Blind, unlimited replay in Dictation, at most two cards).
- G3: Surface decoding failures: a diff of what the learner heard against the real transcript.
- G4: Make repeat failures visible across sessions, for example "gonna" or "could have".
- G5: Keep one session short enough to finish: one clip, one sitting.

**Non-goals (v1)**

- No vocabulary or definition flashcards. Cards hold connected-speech forms only.
- No unrelated speaking tests: grading covers only the learner's shadowing rounds.
- No social features, leaderboards or content marketplace.
- No generated lessons. The learner supplies the content.

**Success metrics**

| Metric | Definition | Target (to confirm) |
| --- | --- | --- |
| Plan completion rate | Sessions that reach the final step / sessions started | 50% or higher |
| Time to first listen | Content added to playback start | Under 60 seconds |
| Return rate | Learners with 3 or more sessions in 14 days | 40% or higher |
| Mark reuse | Cards and shadow segments created from marks / sessions that reached Transcript | 80% or higher |
| Repeat-failure trend | Share of marks that match a pattern marked in an earlier session | Falls over 8 sessions |

## 3. Target users and use cases

The primary user is an intermediate or upper-intermediate English learner (roughly B1 to C1) who understands text well but loses words in fast, natural speech.

| Persona | Need | Typical content |
| --- | --- | --- |
| Exam candidate (IELTS, TOEFL) | Catch every word under test conditions | Lectures, podcasts |
| Working professional | Follow meetings and calls | Interviews, talks, YouTube explainers |
| Self-directed learner | Understand films and series without subtitles | TV clips, vlogs |

**Key use cases**

- UC1: Add a clip by upload or YouTube link and choose a start mode.
- UC2: Transcribe a short passage word for word with unlimited replays, then see exactly what was missed.
- UC3: Listen once without pausing and write a three-sentence gist.
- UC4: Compare what they heard to the transcript and mark each mismatch.
- UC5: Save up to two connected-speech forms as cards.
- UC6: Shadow a 60 to 90 second segment that contains their marks.
- UC7: Resume an unfinished plan, or review marks from earlier sessions.

## 4. The listening plan

The plan has four steps, or five when the learner does both entry exercises; Transcript, Card and Shadow always follow in that order.

&#91;embedded content: listening plan paths · 3 paths, 4 or 5 steps\]

Highlighted boxes are the learner's choice of entry. Read each row left to right.

**Plan rules**

- PL-1: After picking content and a passage, the learner chooses the entry: Blind, Dictation or both. The choice sets the number of steps shown (4 or 5).
- PL-2: Blind and Dictation are the entry exercises. Both give a baseline of what the learner can and cannot hear before any transcript is seen.
- PL-3: Transcript, Card and Shadow always follow, in that order. Marks made in Dictation and Transcript feed Card and Shadow.
- PL-4: If the learner picks both, the default order is Blind first, then Dictation (see OQ-1).
- PL-5: A progress bar shows the current step (for example "Step 3 of 5") and which steps are done.
- PL-6: Step gating follows SS-1 to SS-5 in section 7.
- PL-7: Until the Transcript step starts, the learner can change the entry choice (add or remove Blind or Dictation) and the step count updates. Once Transcript starts, the choice is locked, because Transcript reveals the answers and ends the baseline.

## 5. Content intake

A learner can start a plan from either an uploaded file or a YouTube link, and reaches playback in under 60 seconds.

| ID | Requirement | Priority |
| --- | --- | --- |
| CI-1 | Upload audio or video files (for example MP3, M4A, WAV, MP4, MOV, WEBM). Show upload progress and allow cancel. | Must |
| CI-2 | Accept a YouTube URL, validate it and show title and duration before the plan starts. The server downloads the media and stores it for the learner, so the app controls playback. This stays behind a feature flag until legal review clears it (OQ-6); upload ships first. | Must |
| CI-3 | Let the learner choose the passage to practice: the whole clip, or a start and end time, from 30 seconds to 15 minutes long. Dictation works on a short passage: 2 to 3 minutes by default. | Must |
| CI-4 | Generate a reference transcript with timestamps from the audio, used by Dictation scoring and the Transcript step. For YouTube, use the creator's captions when available, else generate from the downloaded audio. | Must |
| CI-5 | Let the learner correct the reference transcript before Dictation scoring, because an error there makes the diff wrong. | Should |
| CI-6 | Show a clear error for unsupported formats, private or age-restricted videos, and files over the size limit (500 MiB per file, 2 GiB of stored uploads per account; binary units, [ADR 0020](../adr/0020-uploads-confirmed-against-a-pending-upload-table.md)). | Must |
| CI-7 | Save content to a library so a plan can be resumed or repeated later. | Should |

**Rights note.** Uploads are private to the learner. YouTube content is downloaded to our servers so the app has full control of playback. It is stored privately per learner, never shared, shown to others or sold, and deletable by the learner. This breaches YouTube's terms unless legal review finds otherwise, so it is a known risk and YouTube intake stays behind a feature flag until legal review clears it (see risks and OQ-6).

## 6. Practice modes: functional requirements

Each mode has one purpose, enforced rules and a defined output. The five modes are summarized first, then detailed.

| Mode | Purpose | Hard rules | Output |
| --- | --- | --- | --- |
| Dictation | Find which sounds are not heard, with no context bluffing | Word for word, unlimited replays, no transcript visible | Typed text, word-level diff |
| Blind | Train sustained listening and gist | Whole piece, no transcript, no pause, no rewind | Three-sentence gist |
| Transcript | Locate decoding failures | Listen again with transcript; learner marks every sound-vs-text mismatch | Marks (timestamped) |
| Card | Capture connected-speech forms | At most two cards; not vocabulary | Cards (written form + heard form) |
| Shadow | Train rhythm and timing | 60 to 90 seconds containing marks; three rounds | Completed rounds |

### 6.1 Dictation

*Purpose: write out the passage word for word. It is uncomfortable and the most diagnostic exercise, because context cannot cover a missed sound.*

- DI-1: The learner sets the passage length (default 2 to 3 minutes, maximum 15). The player plays that passage only.
- DI-2: Replays are unlimited. Provide replay of the last sentence or segment, plus a slower speed option (default 1x).
- DI-3: The transcript is hidden throughout. No hints, no auto-complete, no spell-check suggestions.
- DI-4: The learner types in a single text area. Draft is auto-saved.
- DI-5: On submit, compare the learner's text with the reference transcript at word level. Highlight missing, wrong and extra words, and show the accuracy percentage. Spelling slips count as correct, are shown separately and are not mark candidates ([ADR 0019](../adr/0019-dictation-scoring-rules.md)).
- DI-6: Each missing or wrong word can be added to the mark list for later steps.

### 6.2 Blind

*Purpose: listen to the whole piece once, resisting the urge to pause.*

- BL-1: Playback controls are limited to start and volume. Pause, seek, rewind and speed change are disabled. Leaving the screen, reloading or seeking ends the attempt, with a warning before leaving. One resume is allowed after an interruption the learner did not cause (a network stall, or a device or OS pause under 5 seconds); a second interruption ends the attempt.
- BL-2: The transcript is hidden throughout.
- BL-3: When playback ends, show a gist prompt asking for three sentences. Require at least three sentences. Grade the gist with AI against the key points of the passage and give the learner a score and written feedback (details in the SRS, section 5.2.1). Grading is about understanding, not spelling or grammar, and never blocks progress.
- BL-4: Show the learner's gist, score, feedback and the captured and missed key points next to the transcript in the Transcript step. Right after Blind, the Blind-then-Dictation path shows only the score, level, rubric scores and the count of key points captured (for example "2 of 4"); the Blind-only path shows everything at once.
- BL-5: The attempt is logged as one pass, with a completion flag.

### 6.3 Transcript

*Purpose: find every place where the sound did not match what is written. These are decoding failures and they repeat.*

- TR-1: Show the transcript synced to audio (current line highlighted), with full controls: pause, seek, replay line, speed.
- TR-2: The learner marks a word or phrase with one tap or click where the sound did not match the text. Each mark stores the text range, timestamp and an optional short note.
- TR-3: Marks from Dictation (DI-6) appear pre-filled and can be confirmed or removed.
- TR-4: A mark can be tagged with a simple type (for example linking, reduction, weak form, unknown word), optional.
- TR-5: Show the count of marks and a list that jumps to the exact audio position.

### 6.4 Card

*Purpose: record the connected-speech form, not the vocabulary meaning.*

- CA-1: A learner creates at most two cards per session. The UI shows "2 left" and blocks a third.
- CA-2: A card is created from a mark. Fields: written form ("could have"), heard form (/kʊdəv/ or a plain respelling), audio snippet auto-cut around the phrase, source link.
- CA-3: No definition or translation field is offered.
- CA-4: Cards live in a deck, reviewable later with the audio snippet played first and the written form revealed after.
- CA-5: Suggest candidate phrases from marks (for example frequent patterns such as "a lot of"), but the learner picks.

### 6.5 Shadow

*Purpose: speak along to match the original's rhythm, timing and sounds, with every round recorded, graded and compared.*

- SH-1: The learner picks a 60 to 90 second segment that contains their marks. The app proposes a default segment centered on the densest cluster of marks and enforces the 60 to 90 second range. When the passage itself is 30 to 60 seconds, the segment is the whole passage.
- SH-2: Three rounds are required. Round 1 shows the transcript. Rounds 2 and 3 hide it.
- SH-3: Playback loops the same segment with a short count-in. Speed stays at the original.
- SH-4: Every round is recorded (required). Each round is graded on rhythm and timing, pronunciation, accent, articulation, fluency, filler words and completeness. After round 3 the system compares the three rounds and gives feedback, repeated mistakes and patterns, and suggestions on how to improve. Accent is shown as guidance ("compared with this speaker") and is not part of the overall round score (details in the SRS, section 5.5.1).
- SH-5: A short reflection prompt after round 3 asks about the hardest part (optional).
- SH-6: The plan is marked complete when all three rounds are done, or when Shadow is skipped.

## 7. Session state, progress and data model

A session is one plan run on one piece of content; it stores which steps are done and carries marks forward from step to step.

**Session rules**

- SS-1: A step unlocks only when the previous step is complete. Learners can leave and resume, except mid-Blind, where leaving voids that pass (one resume is allowed after an interruption the learner did not cause).
- SS-2: Completed steps are read-only, but the learner can repeat a mode as a new attempt.
- SS-3: Marks are the shared spine: Dictation and Transcript write marks, Card and Shadow read them.
- SS-4: A learner cannot skip Transcript, since marks feed the last two steps. Card and Shadow can be skipped with a confirmation.
- SS-5: Progress (current step, drafts, marks) saves automatically.

**Data model**

| Entity | Key fields |
| --- | --- |
| Content | id, owner, source (upload or YouTube), media reference, title, duration, language |
| Transcript | media item and passage time span (shared by every learner using that media), segments (start, end, text), origin (creator captions or generated); a learner's edits are kept as their own corrections |
| Session | id, content id, passage start and end, path (blind, dictation or both), current step, status |
| Attempt | session id, mode, started, finished, completed flag, payload (typed text, gist, rounds) |
| Mark | session id, transcript range, timestamp, note, tag, source (dictation or manual) |
| Card | session id, mark id, written form, heard form, audio snippet range |
| ShadowRound | session id, segment start and end, round number (1 to 3), transcript shown, recording reference |

## 8. Non-functional requirements, scope, risks and open questions

v1 ships the full plan for web, with accurate transcripts as the main technical risk.

### 8.1 Non-functional requirements

- Performance: playback starts within 2 seconds of a step opening. Transcript generation for a 10-minute clip finishes in a time to be set after benchmarking.
- Accuracy: Blind controls must be truly locked; replay and speed controls in Dictation must be frame-accurate to the segment.
- Reliability: drafts and marks are never lost on refresh, tab close or lost connection.
- Privacy: uploads and recordings are private to the account and deletable by the learner. Shadow recordings are kept 90 days, then deleted; grades and word labels stay. A deleted account is disabled at once and can be restored by signing in within 7 days.
- Accessibility: keyboard-operable controls, captions on the UI itself, readable at mobile widths.
- Platforms: responsive web first. Native mobile apps are a later phase.

* AI cost and independence: the MVP uses free-tier or open-source AI only. Every AI provider (transcription, text AI, speech assessment) sits behind a common interface and can be swapped by configuration, so the product is never locked to one vendor and can move to paid models later (SRS, section 8.7).

### 8.2 Analytics events

Track: content added (source type), plan started (path), step started, step completed, replay count in Dictation, Blind abandoned, marks created, cards created, shadow rounds completed. Use these to measure the metrics in section 2.

### 8.3 Release scope

| Phase | Scope |
| --- | --- |
| MVP | Upload intake (YouTube intake behind a feature flag until legal review clears it), generated transcript with per-learner corrections, all five modes with gist grading and Shadow recording and grading, three plan paths, marks, two cards with a review deck, auto-save, simple library, email and Google sign-in |
| v1.1 | Score trends for gists and Shadow measures, with cross-session pattern insights (repeat failures) |
| v2 | Spaced card review, mobile apps |

### 8.4 Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Reference transcript errors | Wrong Dictation diff and false marks | Show confidence, let the learner edit (CI-5), prefer creator captions |
| Server-side YouTube download conflicts with YouTube's terms | Takedown notices, blocked server IPs, app store removal | YouTube intake behind a feature flag until legal review clears it, upload first; private per-learner storage with deletion; no sharing or resale; keep the downloader isolated so it can be switched off, with upload as the fallback |
| Learners skip the hard modes | Plan loses its value | Enforce order, keep steps short, show the benefit of marks |
| Blind lock bypassed by browser tricks | Rule broken, trust lost | Lock controls in-app and treat a leave as a voided pass |

### 8.5 Open questions

- OQ-1 (resolved): With both, Blind comes first, then Dictation.
- OQ-2 (resolved): Every passage is at least 30 seconds and at most 15 minutes; Dictation passages are 2 to 3 minutes by default.
- OQ-3 (resolved): Accounts are required in the MVP, so progress works across browsers and devices.
- OQ-4: (resolved): The learner can change their entry choice (for example from Blind only to Blind plus Dictation) until the Transcript step starts. After that it is locked (see PL-7).
- OQ-5 (resolved): English only, for content, transcripts and the UI.
- OQ-6: Before launch, legal review must confirm three things. (a) Whether YouTube's terms allow reading audio from a video the learner links, or only playing it in the embedded player. (b) Whether generating and storing a transcript of someone else's video is allowed, and how long it may be kept. (c) What the app may do with uploaded files that contain copyrighted material, since learners may upload films and podcasts. Decision: the MVP builds and ships the upload-only path first. YouTube intake (downloaded to our servers for full control) stays behind a feature flag until the legal review clears it, and YouTube media is excluded from data export.
