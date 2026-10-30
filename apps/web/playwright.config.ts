import { defineConfig, devices } from '@playwright/test';

// The smoke test runs against the production build (vite preview) and answers the
// API from the test itself, so it needs no backend.
const port = Number(process.env.E2E_PORT ?? 4173);
// Where a preinstalled Chromium lives when `playwright install` is not available.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

// Cross-browser matrix (#99, NFR-COM-1): chromium runs by default; the nightly and
// release workflows set E2E_BROWSERS=chromium,firefox,webkit,msedge. Edge is the
// Chromium build that Microsoft ships, so it needs `playwright install msedge`.
const browsers = (process.env.E2E_BROWSERS ?? 'chromium').split(',').map((name) => name.trim());
const MATRIX = ['chromium', 'msedge', 'firefox', 'webkit'];
const chromiumArgs = ['--use-fake-device-for-media-stream'];

export default defineConfig({
  testDir: 'e2e',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${port}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: 'a11y.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        // Headless Shell's getUserMedia rejects with NotSupportedError even
        // with a fake device. Full Chromium exercises the real permission path.
        channel: 'chromium',
        permissions: ['microphone'],
        launchOptions: { executablePath, args: chromiumArgs },
      },
    },
    {
      name: 'msedge',
      testIgnore: 'a11y.spec.ts',
      use: {
        ...devices['Desktop Edge'],
        channel: 'msedge',
        permissions: ['microphone'],
        launchOptions: { args: chromiumArgs },
      },
    },
    {
      name: 'firefox',
      testIgnore: 'a11y.spec.ts',
      use: {
        ...devices['Desktop Firefox'],
        launchOptions: {
          // Firefox's own fake microphone, with no permission prompt. Playback also
          // needs an audio sink: on a machine with no sound card, run PulseAudio with a
          // null sink (see the cross-browser workflow) or audio fails to start.
          firefoxUserPrefs: {
            'media.navigator.streams.fake': true,
            'media.navigator.permission.disabled': true,
          },
        },
      },
    },
    {
      // WebKit has no fake device: the shared test fixture (e2e/test.ts) swaps in a
      // Web Audio stream, which the real MediaRecorder records as AAC in MP4.
      name: 'webkit',
      testIgnore: 'a11y.spec.ts',
      use: { ...devices['Desktop Safari'] },
    },
    // The axe scan of every route (#98): desktop, 360 px (UI-4) and the dark theme.
    ...[
      { name: 'a11y-desktop', viewport: { width: 1280, height: 800 } },
      { name: 'a11y-360', viewport: { width: 360, height: 740 } },
      {
        name: 'a11y-dark',
        viewport: { width: 1280, height: 800 },
        colorScheme: 'dark' as const,
      },
    ].map(({ name, ...use }) => ({
      name,
      testMatch: 'a11y.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: { executablePath },
        reducedMotion: 'reduce' as const,
        ...use,
      },
    })),
  ].filter(({ name }) => !MATRIX.includes(name) || browsers.includes(name)),
  webServer: {
    command: `pnpm build && pnpm preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
