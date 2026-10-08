import { expect, test, type Page } from '@playwright/test';

const ADMIN = { id: '1', email: 'ops@example.com', display_name: null, email_verified: true };

const LANES = [
  { lane: 'speech-interactive', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
  { lane: 'intake', waiting: 2, scheduled: 0, running: 1, oldest_wait_seconds: 40 },
  { lane: 'ai', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
  { lane: 'background', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
];

const FAILED = {
  id: 12,
  lane: 'intake',
  name: 'content.convert_upload',
  attempts: 5,
  failed_at: '2026-10-08T09:30:00Z',
};

async function answerApi(page: Page, admin: boolean) {
  let failed = [FAILED];
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: ADMIN });
    if (admin && path === '/admin/jobs') return route.fulfill({ json: { lanes: LANES, failed } });
    if (admin && path === '/admin/jobs/12/retry' && request.method() === 'POST') {
      expect(request.headers()['x-csrf-token']).toBe('e2e-token');
      failed = [];
      return route.fulfill({ status: 202, json: { job_id: 40 } });
    }
    if (path === '/events') return route.abort();
    return route.fulfill({
      status: 404,
      contentType: 'application/problem+json',
      json: { type: '/problems/not_found', title: '', status: 404, detail: '', code: 'not_found' },
    });
  });
}

test('an admin sees the job backlog and retries a failed job', async ({ page }) => {
  await answerApi(page, true);

  await page.goto('/admin/jobs');
  await expect(page.getByRole('heading', { name: 'Jobs', level: 1 })).toBeVisible();
  const intake = page.getByRole('row', { name: /^Intake/ });
  await expect(intake.getByRole('cell')).toHaveText(['2', '0', '1', '40 s']);

  await page.getByRole('button', { name: 'Retry job 12, content.convert_upload' }).click();
  await expect(page.getByText('Job 12 was queued again as job 40.')).toBeVisible();
  await expect(page.getByText('No failed jobs.')).toBeVisible();
});

test('a learner who opens the admin page sees page-not-found', async ({ page }) => {
  await answerApi(page, false);

  await page.goto('/admin/jobs');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
});
