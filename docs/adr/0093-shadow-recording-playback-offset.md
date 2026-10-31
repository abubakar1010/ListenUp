# ADR 0093: The browser reports where the original starts in a Shadow recording

- Status: Accepted (owner, 2026-10-31, option b); the Database Design change and
  the migration are pending
- Story: #82. Related: ADRs 0063, 0070, 0092; #90
- Requirements: FR-SH-4, FR-SH-8, FR-SH-9, AT-17

## Context

Timing compares the learner's word onsets with the original's (Architecture 6), so
both must be on one clock. A recording starts at the count-in (ADR 0070), and the
original then plays after a three-second count-in, or later when the browser refuses
autoplay and the learner presses "Play now" (ADR 0063). The server never learns when
playback began. Assuming 3 s would score an autoplay delay as a late start.
Estimating the offset from the speech would remove a constant lag, so late starts
across a whole round would never count (AT-17).

## Decision

When it finishes a recording, the browser reports `playback_offset_ms`: the
milliseconds from the recorder's start to the original's first `playing` event, both
measured on one monotonic clock (`performance.now()`). The server stores it on the
round. The value must be an integer of 0 or more and no longer than the recording;
the bound goes in the migration.

### Measuring the offset

The fresh-session review of PR #261 found that the first `playing` event alone can
misplace the original. These rules close those gaps:

- **Recorder start** is the `MediaRecorder` `start` event, not the `start()` call.
  The microphone opens asynchronously (`getUserMedia`), so recording can begin late.
- **Playback start** is the round's first `playing` event, corrected for where the
  media really was: offset = (`playing` time − recorder start) − (`currentTime` at
  that event − segment start). A seek that lands a little after the segment start
  then moves the original's words by the same amount.
- **No offset is reported** (null), and timing is null with a reason, when:
  - the corrected offset is negative, because playback began before the recorder
    started; or
  - a `waiting`, `stalled` or `seeking` event occurs after the first `playing` event
    and before the segment ends. A buffering stall shifts every later original word on
    the recording clock, and one offset cannot describe it.

  The round itself is not voided. Its other measures do not use the clock.
- **Audio output latency is not subtracted.** Browsers do not report it reliably
  for media elements, and Bluetooth headphones can add 150–300 ms. It biases every
  onset by the same amount, inside the 0.5 s full-credit window of the version 1
  parameters. #80's real-device checks measure it. Compensation, if needed, is a
  later decision.

The round job places the original's words on the recording clock with
`grading.domain.delivery.place_original` (media time minus the segment start, plus
the offset; words not wholly inside the segment are dropped). Only timing needs the
clock: fluency compares gaps between the same two words, and fillers and
completeness use counts and the passage's length. A round with no offset gets a null
timing score with a reason. It never gets an assumed count-in.

## Consequences

- `practice.shadow_rounds` gains a nullable `playback_offset_ms`. Database Design
  §5 must list it before the migration lands. That document belongs to its owner
  for this wave, so the change is requested, not made here.
- The recording completion request and the web Shadow recorder gain the field.
  `pnpm api:generate` and the OpenAPI export follow. Existing rounds have no offset.
- The offset is measured in the browser, which `performance.now()` precision and
  audio output latency bound. Playback-start accuracy is not validated here; it joins
  #80's real-device checks.
- The web recorder must listen for `waiting`, `stalled` and `seeking` during a round.
  Today's Shadow player handles none of them while it plays.

## Continuation scope (2026-10-31)

The approved #82 continuation consumes an absent offset explicitly and records
`timing.score = null` with `playback_offset_unknown`; fluency, fillers and
completeness still use original timings. The migration in this continuation adds
`round_grades` and the round ownership key only. It does not add the offset column,
change recording request schemas or change the browser. The design update, browser
measurement and offset persistence above remain pending with their owners. There
is no assumed three-second count-in and no speech-derived offset.
