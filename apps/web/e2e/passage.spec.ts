import { expect, test, type Page, type Route } from '@playwright/test';

// The passage picker (#42) against a mocked API. Peaks and audio are generated here, so no
// binary fixture is committed.

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};

function clip(durationMs: number) {
  return {
    id: 'clip-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: durationMs,
    created_at: '2026-10-03T09:00:00Z',
    error_code: null,
    error_detail: null,
    has_video: false,
    keep_video: false,
    media_object_id: 'm-1',
    media_url: '/api/v1/media/m-1',
    peaks_url: '/api/v1/media/m-1/peaks',
  };
}

/** The conversion job's peaks file: `silentS` seconds of room tone, then speech. */
function peaks(silentS: number, durationMs: number) {
  const count = Math.ceil(durationMs / 100);
  return {
    version: 1,
    per_second: 10,
    scale: 100,
    peaks: Array.from({ length: count }, (_, i) =>
      i < silentS * 10 ? 2 : 30 + Math.round(40 * Math.abs(Math.sin(i / 7))),
    ),
  };
}

/** A quiet 8 kHz, 8-bit mono WAV of `seconds`, for "Hear start" and "Hear end". */
function wav(seconds: number): Buffer {
  const rate = 8000;
  const samples = rate * seconds;
  const buffer = Buffer.alloc(44 + samples);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples, 4);
  buffer.write('WAVEfmt ', 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); // PCM
  buffer.writeUInt16LE(1, 22); // mono
  buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate, 28);
  buffer.writeUInt16LE(1, 32);
  buffer.writeUInt16LE(8, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples, 40);
  for (let i = 0; i < samples; i += 1) {
    buffer[44 + i] = 128 + Math.round(20 * Math.sin((2 * Math.PI * 220 * i) / rate));
  }
  return buffer;
}

/** The session `POST /sessions` creates: Blind first, nothing done yet. */
function session(passage: unknown) {
  const steps = ['blind', 'transcript', 'card', 'shadow'].map((step, index) => ({
    step,
    position: index + 1,
    status: index === 0 ? 'open' : 'locked',
  }));
  return {
    id: 's-1',
    content_id: 'clip-1',
    content_title: 'Why cities plant street trees',
    passage,
    entry: 'blind',
    status: 'active',
    version: 0,
    steps,
    step_count: 4,
    open_step: 'blind',
    open_position: 1,
    entry_locked: false,
    entry_locked_at: null,
    completed_at: null,
    created_at: '2026-10-03T09:00:00Z',
    updated_at: '2026-10-03T09:00:00Z',
  };
}

async function fakeApi(page: Page, durationMs: number, silentS = 0) {
  const posts: unknown[] = [];
  const audio = wav(Math.ceil(durationMs / 1000));
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
    if (path === '/contents/clip-1') return route.fulfill({ json: clip(durationMs) });
    // The API redirects these to signed storage URLs; Playwright does not route requests
    // that follow a redirect, so the files are answered here directly.
    if (path === '/media/m-1/peaks') return route.fulfill({ json: peaks(silentS, durationMs) });
    if (path === '/media/m-1') return media(route, audio);
    if (path === '/sessions' && request.method() === 'POST') {
      const body = request.postDataJSON() as { passage: unknown };
      posts.push(body);
      return route.fulfill({ status: 201, json: session(body.passage) });
    }
    return route.fulfill({
      status: 404,
      contentType: 'application/problem+json',
      json: {
        type: '/problems/not_found',
        title: '',
        status: 404,
        detail: path,
        code: 'not_found',
      },
    });
  });
  return { posts };
}

/** Answers range requests, as object storage does, so the player can seek. */
function media(route: Route, audio: Buffer) {
  const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()['range'] ?? '');
  const from = range ? Number(range[1]) : 0;
  const to = range && range[2] ? Number(range[2]) : audio.length - 1;
  return route.fulfill({
    status: range ? 206 : 200,
    headers: {
      'Content-Type': 'audio/wav',
      'Accept-Ranges': 'bytes',
      ...(range ? { 'Content-Range': `bytes ${from}-${to}/${audio.length}` } : {}),
    },
    body: audio.subarray(from, to + 1),
  });
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test('at 360 px, the keyboard alone chooses a part of a long clip', async ({ page }) => {
  const { posts } = await fakeApi(page, 2_285_000, 40);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/contents/clip-1/plan');

  const whole = page.getByRole('radio', { name: /Whole clip · 38:05/ });
  await expect(whole).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('radio', { name: /A part of it/ })).toBeChecked();
  const start = page.getByRole('slider', { name: 'Passage start' });
  const end = page.getByRole('slider', { name: 'Passage end' });
  const startField = page.getByRole('textbox', { name: 'Start' });
  const endField = page.getByRole('textbox', { name: 'End' });

  // 2:30 from the first speech (40 s in), less a half-second lead-in.
  await expect(startField).toHaveValue('00:39');
  await expect(endField).toHaveValue('03:09');
  await expect(page.getByText('2:30 long')).toBeVisible();

  // Focus order: the mode choice, the two handles, the two fields, then the checks.
  await page.getByRole('radio', { name: /A part of it/ }).focus();
  await page.keyboard.press('Tab');
  await expect(start).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Shift+ArrowRight');
  await expect(start).toHaveAttribute('aria-valuetext', '45 seconds');
  await expect(startField).toHaveValue('00:45');

  await page.keyboard.press('Tab');
  await expect(end).toBeFocused();
  await page.keyboard.press('End');
  // The end stops 15 minutes after the start.
  await expect(endField).toHaveValue('15:45');
  await expect(page.getByText('15:00 long')).toBeVisible();
  await page.keyboard.press('PageDown');
  await page.keyboard.press('ArrowLeft');
  await expect(endField).toHaveValue('15:39');
  await expect(page.getByRole('status').filter({ hasText: 'selected' })).toHaveText(
    '14 minutes 54 seconds selected',
  );

  await page.keyboard.press('Tab');
  await expect(startField).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(endField).toBeFocused();
  await endField.fill('23:20');
  await page.keyboard.press('Tab');
  await expect(endField).toHaveValue('15:45');
  await expect(endField).toHaveAccessibleDescription(
    'Start 00:45 to end 23:20 makes 22:35. A part can be 15 minutes at most, so we set the end to 15:45.',
  );
  await expect(page.getByRole('button', { name: 'Hear start' })).toBeFocused();
  await noHorizontalOverflow(page);

  await page.getByRole('button', { name: 'Start plan' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL('/sessions/s-1');
  expect(posts).toEqual([
    { content_id: 'clip-1', passage: { start_ms: 45_000, end_ms: 945_000 }, entry: 'blind' },
  ]);
});

test('dragging a handle snaps to whole seconds and moves the fields', async ({ page }) => {
  await fakeApi(page, 600_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/contents/clip-1/plan');

  await page.getByRole('radio', { name: /A part of it/ }).check();
  const end = page.getByRole('slider', { name: 'Passage end' });
  const endField = page.getByRole('textbox', { name: 'End' });
  await expect(endField).toHaveValue('02:30');

  const handle = (await end.boundingBox())!;
  const track = (await page.getByTestId('waveform-bars').boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(track.x + track.width * 0.5, handle.y + handle.height / 2, { steps: 8 });
  await page.mouse.up();

  await expect(end).toBeFocused();
  const seconds = Number(await end.getAttribute('aria-valuenow'));
  expect(seconds).toBeGreaterThan(290);
  expect(seconds).toBeLessThan(310);
  const shown = await endField.inputValue();
  expect(shown).toBe(
    `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`,
  );

  // A press on the track left of the start moves the start there.
  await page.mouse.click(track.x + 2, track.y + track.height / 2);
  await expect(page.getByRole('textbox', { name: 'Start' })).toHaveValue('00:00');
});

test('"Hear start" plays about 3 s around the start, then stops', async ({ page }) => {
  await fakeApi(page, 200_000);
  await page.goto('/contents/clip-1/plan');
  await page.getByRole('radio', { name: /A part of it/ }).check();
  await page.getByRole('textbox', { name: 'Start' }).fill('00:20');
  await page.getByRole('textbox', { name: 'Start' }).press('Tab');

  await page.getByRole('button', { name: 'Hear start' }).click();
  const audio = page.locator('audio');
  await expect
    .poll(() => audio.evaluate((el: HTMLAudioElement) => !el.paused && el.currentTime > 18.5))
    .toBe(true);
  await expect
    .poll(() => audio.evaluate((el: HTMLAudioElement) => el.paused), { timeout: 6000 })
    .toBe(true);
  const stoppedAt = await audio.evaluate((el: HTMLAudioElement) => el.currentTime);
  expect(stoppedAt).toBeGreaterThanOrEqual(21);
  expect(stoppedAt).toBeLessThan(22.5);
});
