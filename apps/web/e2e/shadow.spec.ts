import { expect, test } from '@playwright/test';
import { sessionFixture } from '../src/features/session/fixtures';

for (const duration of [45_000, 150_000]) {
  test(`Shadow keyboard selection at 360 px for a ${duration / 1000}s passage`, async ({
    page,
  }) => {
    const session = sessionFixture({
      done: 3,
      passage: { start_ms: 10_000, end_ms: 10_000 + duration },
    });
    let segment = {
      session_id: session.id,
      start_ms: 10_000,
      end_ms: 10_000 + Math.min(90_000, duration),
      chosen_by: 'system',
      mark_count: 3,
      locked_at: null,
    };
    const writes: unknown[] = [];
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/api/v1', '');
      if (path === '/health')
        return route.fulfill({
          json: { status: 'ok' },
          headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
        });
      if (path === '/me')
        return route.fulfill({
          json: {
            id: '1',
            email: 'learner@example.com',
            display_name: null,
            email_verified: true,
            deletion_grace_days: 7,
            consents_required: [],
          },
        });
      if (path === `/sessions/${session.id}`) return route.fulfill({ json: session });
      if (path === `/sessions/${session.id}/shadow/segment`) {
        if (request.method() === 'PUT') {
          writes.push(request.postDataJSON());
          segment = { ...segment, ...request.postDataJSON(), chosen_by: 'learner' };
        }
        return route.fulfill({ json: segment });
      }
      if (path === '/contents/clip-1')
        return route.fulfill({
          json: { id: 'clip-1', media_url: '/api/v1/media/m-1', peaks_url: null },
        });
      if (path === '/media/m-1') {
        const audio = wav();
        const requested = /bytes=(\d+)-(\d*)/.exec(request.headers()['range'] ?? '');
        const from = requested ? Number(requested[1]) : 0;
        const to = requested?.[2] ? Number(requested[2]) : audio.length - 1;
        return route.fulfill({
          status: requested ? 206 : 200,
          headers: {
            'Content-Type': 'audio/wav',
            'Accept-Ranges': 'bytes',
            ...(requested ? { 'Content-Range': `bytes ${from}-${to}/${audio.length}` } : {}),
          },
          body: audio.subarray(from, to + 1),
        });
      }
      return route.fulfill({ status: 404, json: { code: 'not_found' } });
    });
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`/sessions/${session.id}`);
    await expect(page.getByRole('heading', { name: 'Your Shadow segment' })).toBeVisible();
    if (duration === 45_000) {
      await expect(
        page.getByText('This passage is 60 seconds or shorter, so Shadow uses the whole passage.'),
      ).toBeVisible();
      await expect(page.getByRole('slider', { name: /Segment (start|end)/ })).toHaveCount(0);
      expect(writes).toEqual([]);
    } else {
      const start = page.getByRole('slider', { name: 'Segment start' });
      await start.focus();
      await start.press('End');
      await expect(start).toHaveAttribute('aria-valuenow', '30');
      await page.keyboard.press('Tab');
      const end = page.getByRole('slider', { name: 'Segment end' });
      await expect(end).toBeFocused();
      await end.press('End');
      await page.keyboard.press('Tab');
      await expect(page.getByRole('button', { name: 'Save segment' })).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(page.getByText('Segment saved.')).toBeVisible();
      expect(writes).toEqual([{ start_ms: 40_000, end_ms: 130_000 }]);
      await page.reload();
      await expect(page.getByRole('slider', { name: 'Segment start' })).toHaveAttribute(
        'aria-valuenow',
        '30',
      );
      await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeEnabled();
      await page.getByRole('slider', { name: 'Seek', exact: true }).fill('50000');
      await page.getByRole('button', { name: 'Replay selected segment' }).click();
      await expect
        .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime))
        .toBeGreaterThanOrEqual(40);
      expect(
        await page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.currentTime),
      ).toBeLessThan(42);
      await page.locator('audio').evaluate((audio: HTMLAudioElement) => {
        audio.currentTime = 130.1;
        audio.dispatchEvent(new Event('timeupdate'));
      });
      await expect
        .poll(() => page.locator('audio').evaluate((audio: HTMLAudioElement) => audio.paused))
        .toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);
  });
}

function wav(): Buffer {
  const samples = 200 * 8000;
  const buffer = Buffer.alloc(44 + samples, 128);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(8000, 24);
  buffer.writeUInt32LE(8000, 28);
  buffer.writeUInt16LE(1, 32);
  buffer.writeUInt16LE(8, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples, 40);
  return buffer;
}
