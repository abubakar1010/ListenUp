import { defineConfig, devices } from '@playwright/test';

// The smoke test runs against the production build (vite preview) and answers the
// API from the test itself, so it needs no backend.
const port = Number(process.env.E2E_PORT ?? 4173);
// Where a preinstalled Chromium lives when `playwright install` is not available.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

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
        permissions: ['microphone'],
        launchOptions: {
          executablePath,
          args: ['--use-fake-device-for-media-stream'],
        },
      },
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
  ],
  webServer: {
    command: `pnpm build && pnpm preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
