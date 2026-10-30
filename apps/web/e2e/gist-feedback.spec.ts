import { expect, test } from './test';
import { sessionFixture } from '../src/features/session/fixtures';

for (const entry of ['blind', 'both'] as const) {
  test(`full gist beside transcript at 360px on ${entry} path`, async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    const session = sessionFixture({ entry, done: entry === 'both' ? 2 : 1 });
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
      if (path === '/me')
        return route.fulfill({
          json: {
            id: 'learner-69',
            email: 'test@example.com',
            display_name: null,
            email_verified: false,
            deletion_grace_days: 7,
            consents_required: [],
          },
        });
      if (path === '/sessions/session-1') return route.fulfill({ json: session });
      if (path === '/sessions/session-1/blind')
        return route.fulfill({ json: { attempt: { id: 'gist-69', status: 'submitted' } } });
      if (path === '/gists/gist-69/grade')
        return route.fulfill({
          json: {
            status: 'ready',
            overall: 80,
            level: 'good',
            dimension_scores: { main_idea: 90, key_details: 70, accuracy: 80 },
            captured_count: 1,
            total_count: 2,
            gist: 'My gist with a long word: ' + 'a'.repeat(200),
            feedback: 'You caught the main idea. Read the other detail.',
            key_points: [
              { text: 'Main idea', captured: true },
              { text: 'Another detail ' + 'b'.repeat(200), captured: false },
            ],
          },
        });
      if (path === '/sessions/session-1/transcript')
        return route.fulfill({
          json: {
            session_id: session.id,
            passage: session.passage,
            media_url: '/api/v1/media/test',
            lines: [
              {
                index: 0,
                start_ms: 130000,
                end_ms: 132000,
                words: [{ index: 0, text: 'Hello', start_ms: 130000, end_ms: 132000 }],
              },
            ],
          },
        });
      if (path === '/sessions/session-1/marks') return route.fulfill({ json: { marks: [] } });
      return route.fulfill({ status: 404, json: { code: 'not_found' } });
    });
    await page.goto('/sessions/session-1');
    await expect(page.getByRole('button', { name: 'Jump to Hello' })).toBeVisible();
    const panel = page.getByRole('region', { name: 'Gist feedback' });
    await expect(panel.getByText('Captured: Main idea')).toBeVisible();
    await expect(panel.getByText(/Missed: Another detail/)).toBeVisible();
    await expect(panel.getByText('You caught the main idea. Read the other detail.')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
    await page.setViewportSize({ width: 1280, height: 900 });
    const transcript = await page.locator('[data-slot="work"]').boundingBox();
    const aside = await page.locator('[data-slot="aside"]').boundingBox();
    expect(aside!.x).toBeGreaterThanOrEqual(transcript!.x + transcript!.width);
  });
}
