/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

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
  },
});
