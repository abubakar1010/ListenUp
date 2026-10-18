import { expect, test } from '@playwright/test';

const PASSAGE = { start_ms: 0, end_ms: 30000 };
const SESSION = {
  id: 's-57',
  content_id: 'c-57',
  content_title: 'Transcript practice',
  passage: PASSAGE,
  entry: 'dictation',
  status: 'active',
  version: 1,
  steps: [
    { step: 'dictation', position: 1, status: 'done' },
    { step: 'transcript', position: 2, status: 'open' },
    { step: 'card', position: 3, status: 'locked' },
    { step: 'shadow', position: 4, status: 'locked' },
  ],
  step_count: 4,
  open_step: 'transcript',
  open_position: 2,
  entry_locked: true,
  entry_locked_at: '2026-10-18T00:00:00Z',
  completed_at: null,
  created_at: '2026-10-18T00:00:00Z',
  updated_at: '2026-10-18T00:00:00Z',
};
function wav(): Buffer {
  const samples = 8000 * 35;
  const data = Buffer.alloc(44 + samples, 128);
  data.write('RIFF');
  data.writeUInt32LE(36 + samples, 4);
  data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16);
  data.writeUInt16LE(1, 20);
  data.writeUInt16LE(1, 22);
  data.writeUInt32LE(8000, 24);
  data.writeUInt32LE(8000, 28);
  data.writeUInt16LE(1, 32);
  data.writeUInt16LE(8, 34);
  data.write('data', 36);
  data.writeUInt32LE(samples, 40);
  return data;
}
const AUDIO = wav();

test('transcript_keyboard_controls_at_360px', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace('/api/v1', '');
    if (path === '/me')
      return route.fulfill({
        json: {
          id: 'learner-57',
          email: 'test@example.com',
          display_name: null,
          email_verified: false,
          deletion_grace_days: 7,
        },
      });
    if (path === '/sessions/s-57') return route.fulfill({ json: SESSION });
    if (path === '/sessions/s-57/transcript')
      return route.fulfill({
        json: {
          session_id: 's-57',
          passage: PASSAGE,
          media_url: '/api/v1/media/m-57',
          lines: [
            {
              index: 0,
              start_ms: 0,
              end_ms: 1000,
              words: [{ index: 0, text: 'Hello.', start_ms: 0, end_ms: 1000, edited: true }],
            },
            {
              index: 1,
              start_ms: 10000,
              end_ms: 12000,
              words: [{ index: 1, text: 'Again.', start_ms: 10000, end_ms: 12000 }],
            },
          ],
        },
      });
    if (path === '/media/m-57') {
      const range = /bytes=(\d+)-(\d*)/.exec(req.headers()['range'] ?? '');
      const start = range ? Number(range[1]) : 0;
      const end = range?.[2] ? Number(range[2]) : AUDIO.length - 1;
      return route.fulfill({
        status: range ? 206 : 200,
        body: AUDIO.subarray(start, end + 1),
        headers: {
          'Content-Type': 'audio/wav',
          'Accept-Ranges': 'bytes',
          ...(range ? { 'Content-Range': `bytes ${start}-${end}/${AUDIO.length}` } : {}),
        },
      });
    }
    if (path === '/events')
      return route.fulfill({ contentType: 'text/event-stream', body: ': connected\n\n' });
    return route.fulfill({ json: { status: 'ok' } });
  });
  await page.goto('/sessions/s-57');
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeEnabled();
  await expect(page.getByText('Entry locked')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Jump to Hello. (edited)' })).toContainText(
    'Edited',
  );
  const second = page.getByRole('button', { name: 'Jump to Again.' });
  // Reach the word through keyboard traversal and activate its native button.
  await page.getByRole('combobox', { name: 'Speed' }).focus();
  for (let i = 0; i < 8 && !(await second.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press('Tab');
  }
  await expect(second).toBeFocused();
  await page.keyboard.press('Enter');
  const current = page.locator('[aria-current="true"]');
  await expect(current).toContainText('Again.');
  await expect(current).toContainText('Current line');
  expect(await current.evaluate((el) => getComputedStyle(el).borderLeftWidth)).toBe('4px');
  await expect(second).toBeFocused();
  await page.getByRole('button', { name: 'Replay line' }).focus();
  await page.keyboard.press('Space');
  await expect
    .poll(() => page.locator('audio').evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeLessThan(11);
  await page.getByRole('combobox', { name: 'Speed' }).focus();
  await page.keyboard.press('ArrowDown');
  await expect
    .poll(() => page.locator('audio').evaluate((el: HTMLAudioElement) => el.playbackRate))
    .toBe(0.9);
  const seek = page.getByRole('slider', { name: 'Seek' });
  await seek.focus();
  await page.keyboard.press('ArrowRight');
  await expect
    .poll(() => page.locator('audio').evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeGreaterThan(10.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
