import { type Page } from '@playwright/test';
import { expect, onMacWebKit, test } from './test';

const ADMIN = {
  id: '1',
  email: 'ops@example.com',
  display_name: null,
  email_verified: true,
  consents_required: [],
};

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
    if (admin && path === '/admin/usage')
      return route.fulfill({
        json: {
          start_date: '2026-10-01',
          end_date: '2026-10-30',
          as_of: '2026-10-30T23:30:00Z',
          providers: [
            {
              provider: 'hosted',
              days: [
                {
                  date: '2026-10-30',
                  calls: 2,
                  input_tokens: 300,
                  output_tokens: 50,
                  audio_seconds: 4,
                  estimated_cost_usd: 0.25,
                  estimated_calls: 1,
                },
              ],
              quotas: [
                {
                  period: 'day',
                  calls: 2,
                  tokens: 350,
                  audio_seconds: 4,
                  limits: { calls: 10, tokens: 1000 },
                },
              ],
            },
          ],
        },
      });
    if (admin && path === '/admin/jobs') return route.fulfill({ json: { lanes: LANES, failed } });
    if (admin && path === '/admin/jobs/12/retry' && request.method() === 'POST') {
      // Playwright's WebKit on macOS does not show these request headers to the test.
      if (!onMacWebKit()) expect(request.headers()['x-csrf-token']).toBe('e2e-token');
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

test('at 360 px the job tables scroll inside their own regions, not the page', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await answerApi(page, true);

  await page.goto('/admin/jobs');
  await expect(page.getByRole('table', { name: 'Failed jobs, newest first' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);

  for (const name of ['Backlog table', 'Failed jobs table']) {
    const region = page.getByRole('region', { name });
    await region.focus();
    await expect(region).toBeFocused();
  }
  const retry = page.getByRole('button', { name: 'Retry job 12, content.convert_upload' });
  await retry.focus();
  await expect(retry).toBeInViewport();
});

test('a learner who opens the admin page sees page-not-found', async ({ page }) => {
  await answerApi(page, false);

  await page.goto('/admin/jobs');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
});

test('an admin navigates to usage by keyboard and reads it at 360 px', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await answerApi(page, true);
  await page.goto('/admin/jobs');
  const usage = page.getByRole('link', { name: 'AI usage', exact: true });
  await usage.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/admin\/usage$/);
  await expect(page.getByRole('table', { name: 'hosted daily usage (UTC)' })).toBeVisible();
  await expect(page.getByText('2 / 10 (20%)')).toBeVisible();
  await expect(page.getByText('$0.2500')).toBeAttached();
  const history = page.getByRole('region', { name: 'hosted history' });
  await history.focus();
  await expect(history).toBeFocused();
  await page.keyboard.press('End');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('link', { name: 'Jobs', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/jobs$/);
});

test('a learner who opens usage receives the ordinary page-not-found', async ({ page }) => {
  await answerApi(page, false);
  await page.goto('/admin/usage');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
});
