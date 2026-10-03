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
      use: { ...devices['Desktop Chrome'], launchOptions: { executablePath } },
    },
  ],
  webServer: {
    command: `pnpm build && pnpm preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
