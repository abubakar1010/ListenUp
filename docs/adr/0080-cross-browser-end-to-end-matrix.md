# ADR 0080: Cross-browser end-to-end matrix

- Status: Accepted
- Date: 2026-10-28
- Story: [#99](https://github.com/abubakar1010/ListenUp/issues/99)
- Requirements: NFR-COM-1; AT-2, AT-5 to AT-8, AT-16 ([SRS 9.1](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd)); Architecture 12.4

## Context

Accounts exist so a learner can move between browsers (NFR-COM-1: current Chrome, Edge, Safari and Firefox), and recording and media differ by engine: Safari records AAC in MP4 where Chrome and Firefox record Opus in WebM (FR-SH-5). The Playwright suite ran on Chromium only. It answers the API from the tests, so it proves what a browser does with the interface and media, never the server.

## Decision

- **One suite, four projects.** `chromium`, `msedge`, `firefox` and `webkit` run the whole existing suite (no copy for other browsers). `E2E_BROWSERS` (comma-separated, default `chromium`) selects the projects, so `pnpm e2e` and the per-push CI job stay quick and need only Chromium.
- **Nightly and before release.** `.github/workflows/cross-browser.yml` runs one job per browser every night and on demand. The on-demand run is the pre-release check: the runbook says to run it on the commit that ships. It is not wired into `release.yml`, which fires on every green push to `main` and also performs rollbacks; making the owner's release wait for a 4-browser matrix is the owner's decision.
- **Fake microphone per engine.** Chromium and Edge: `--use-fake-device-for-media-stream`. Firefox: `media.navigator.streams.fake`. WebKit has no such switch, so `e2e/test.ts` gives it a Web Audio oscillator stream; the page records it with the real `MediaRecorder`.
- **Recording format is asserted per engine.** The Shadow test checks the declared type and, where Playwright exposes the request body, the container bytes (EBML for WebM, `ftyp` for MP4). A second variant refuses WebM the way an older Safari does and requires `audio/mp4`. Firefox without MP4 recording skips that variant; Linux WebKit without `MediaRecorder` skips the recording tests. All other missing recording capabilities fail. These exceptions are reported as skipped, never as passed.
- **WebKit runs on macOS.** Playwright's Linux WebKit has no `MediaRecorder` and cannot fulfil a redirect response from a mock (three tests skip with a stated reason, `WEBKIT_NO_REDIRECT_MOCK`), and its request bodies are unreadable. The macOS build is the one that records.
- **Firefox needs an audio sink.** On a machine without a sound card, Firefox fails to start playback (`OnMediaSinkAudioError`), which breaks Blind. The job starts PulseAudio with a null sink. That job only: with PulseAudio present, Chromium's fake microphone check never hears a sound.

- **Safari's keyboard and focus rules are followed on macOS WebKit.** Tab skips buttons and links there unless Full Keyboard Access is on, so the shared fixture presses Option+Tab in its place (macOS WebKit only). A mouse click does not focus a button, so the specs that need a focused opener open it from the keyboard. A native `<select>` opens its menu on the arrow keys, so the two specs that change a select by arrow key skip on macOS WebKit (a manual check). Request headers and Blob bodies are not visible to a test there, so those assertions are skipped on it only; the client and API tests cover them. Every omitted assertion has a named skipped step and a `skipped-check` report annotation; a passing flow does not claim that assertion passed. Blob-body checks are similarly reported on WebKit.

## Consequences

- This is not Safari. Real Safari on macOS and iOS and Chrome on Android stay manual checks listed in the pull request.
- The mocked suite cannot show that the server enforces the Blind rules (AT-2); the API integration tests do.
- The nightly run uses runner minutes (macOS is the dearest); drop the schedule, keeping the manual run, if that matters.
