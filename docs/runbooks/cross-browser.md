# Cross-browser end-to-end run

Why and what each project does: [ADR 0080](../adr/0080-cross-browser-end-to-end-matrix.md). The suite answers the API from the tests: it proves browser behaviour, not the server.

## Before a release

1. Actions → **Cross-browser** → Run workflow, on `main` (or the commit that ships).
2. All four jobs (chromium, msedge, firefox, webkit) must be green. A skipped test is listed in the report with its reason; read the skips, since they are the cases a browser cannot run.
3. Do the manual checks below.

The workflow also runs every night; a red night means a browser difference reached `main`.

## Locally

```bash
cd apps/web
pnpm exec playwright install chromium firefox webkit   # msedge: playwright install msedge
E2E_BROWSERS=chromium,firefox,webkit pnpm e2e
```

- Firefox needs an audio output. With no sound card: `pulseaudio --start --exit-idle-time=-1 && pactl load-module module-null-sink sink_name=ci`. Stop PulseAudio again before running Chromium (`pulseaudio --kill`), or the fake microphone check fails.
- On Linux, WebKit needs `playwright install-deps webkit`; it has no `MediaRecorder`, so the Shadow recording tests skip. They run in the macOS job.
- Where Chromium cannot be installed, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

## Known differences

- macOS WebKit (Safari's engine): Tab skips buttons and links, so the fixture presses Option+Tab; a mouse click does not focus a button; the arrow keys open a native select instead of changing it (two specs skip on macOS WebKit for this); request headers and Blob bodies are not visible to the test. See ADR 0080.
- Firefox starts audio about 2 s late behind a null sink, so "Hear start" (stopped by a 3 s wall-clock timer) plays about 1 s; its test accepts that on Firefox only and records a `finding` annotation.
- The admin "retry a failed job" test is occasionally flaky on WebKit (it also fails about 1 in 10 on the original spec); CI retries once.

## Manual checks (the owner's)

Per release, on real devices at 360 px and a desktop width: sign in, run a Blind listen, a Dictation, a Card and one Shadow round (the recording replays), and sign in on a second device to find the same sessions, marks and cards.

- Safari on macOS and on iOS (Shadow records AAC in MP4 on versions without WebM recording).
- Chrome on Android.
