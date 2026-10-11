/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Keep test helpers and generated schema types in one list shared with the
// coverage completeness check. The API contract job checks generated types.
const coverageExclusions: string[] = JSON.parse(
  readFileSync(new URL('./coverage-exclusions.json', import.meta.url), 'utf8'),
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The API runs on port 8000 (Docker Compose); the browser only ever calls /api.
    // LISTENUP_API_URL points the proxy at another API, for example a second checkout.
    proxy: { '/api': process.env.LISTENUP_API_URL ?? 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    // Playwright owns e2e/; Vitest runs the unit and component tests in src/.
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      // Include runtime modules even when no test imports them.
      include: ['src/**/*.{ts,tsx}'],
      exclude: coverageExclusions,
      reportsDirectory: 'coverage',
      // Both reports use app-relative paths so artifact consumers work in any checkout.
      reporter: ['text-summary', 'json-summary', ['cobertura', { projectRoot: '.' }], 'html'],
      reportOnFailure: true,
    },
  },
});
