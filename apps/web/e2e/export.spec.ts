import { expect, test } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};

const PENDING = {
  id: 'e1',
  status: 'pending',
  requested_at: '2026-10-04T09:00:00Z',
  ready_at: null,
  expires_at: null,
  archive_bytes: null,
  file_count: null,
  download_url: null,
};

const READY = {
  ...PENDING,
  status: 'ready',
  ready_at: '2026-10-04T09:02:00Z',
  expires_at: '2026-10-11T09:02:00Z',
  archive_bytes: 3 * 1024 * 1024,
  file_count: 1,
  download_url: '/api/v1/me/exports/e1/download',
};

test('a learner asks for a copy of their data and gets a download link', async ({ page }) => {
  let latest: typeof PENDING | typeof READY | null = null;
  let checks = 0;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/me/exports' && request.method() === 'POST') {
      expect(request.headers()['x-csrf-token']).toBe('e2e-token');
      latest = PENDING;
      return route.fulfill({ status: 202, json: PENDING });
    }
    if (path === '/me/exports/latest') {
      // The build finishes after a couple of checks (the page polls without live events).
      if (latest === PENDING && ++checks > 1) latest = READY;
      return route.fulfill({ json: { export: latest } });
    }
    if (path === '/events') return route.abort();
    return route.fulfill({
      status: 404,
      contentType: 'application/problem+json',
      json: { type: '/problems/not_found', title: '', status: 404, detail: path, code: 'x' },
    });
  });

  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
  const section = page.getByRole('region', { name: 'Download your data' });
  await section.getByRole('button', { name: 'Prepare my download' }).click();
  await expect(section.getByRole('status')).toContainText('We are preparing your download');

  const link = section.getByRole('link', { name: 'Download your data (ZIP)' });
  await expect(link).toBeVisible({ timeout: 15_000 });
  await expect(link).toHaveAttribute('href', '/api/v1/me/exports/e1/download');
  await expect(section.getByRole('status')).toContainText('3.0 MB, 1 media file');
});
