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

## Manual checks (the owner's)

Per release, on real devices at 360 px and a desktop width: sign in, run a Blind listen, a Dictation, a Card and one Shadow round (the recording replays), and sign in on a second device to find the same sessions, marks and cards.

- Safari on macOS and on iOS (Shadow records AAC in MP4 on versions without WebM recording).
- Chrome on Android.
