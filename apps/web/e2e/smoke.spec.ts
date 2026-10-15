import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';

import { expect, test, type Page } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
  deletion_grace_days: 7,
};

const SESSION = {
  id: 'abc-123',
  content_id: 'clip-1',
  content_title: 'Why cities plant street trees',
  passage: { start_ms: 130_000, end_ms: 280_000 },
  entry: 'blind',
  status: 'active',
  version: 0,
  steps: ['blind', 'transcript', 'card', 'shadow'].map((step, index) => ({
    step,
    position: index + 1,
    status: index === 0 ? 'open' : 'locked',
  })),
  step_count: 4,
  open_step: 'blind',
  open_position: 1,
  entry_locked: false,
  entry_locked_at: null,
  completed_at: null,
  created_at: '2026-10-03T09:00:00Z',
  updated_at: '2026-10-03T09:00:00Z',
};

/** Answers the API in the browser: signed out until the login call succeeds. */
async function fakeApi(page: Page, { signedIn = false } = {}) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/auth/login') {
      signedIn = true;
      return route.fulfill({ json: LEARNER });
    }
    if (path === '/me' && signedIn) return route.fulfill({ json: LEARNER });
    if (signedIn) {
      // Endpoints this test does not fake: an empty answer, not a sign-out.
      if (path === '/library/contents' || path === '/sessions')
        return route.fulfill({ json: { items: [], next_cursor: null } });
      if (path === '/sessions/abc-123') return route.fulfill({ json: SESSION });
      if (path === '/sessions/abc-123/blind') {
        return route.fulfill({
          json: {
            session_id: 'abc-123',
            passage_start_ms: 130_000,
            passage_end_ms: 280_000,
            step_status: 'open',
            attempt: null,
          },
        });
      }
      return route.fulfill({
        status: 404,
        contentType: 'application/problem+json',
        json: {
          type: '/problems/not_found',
          title: 'Not Found',
          status: 404,
          detail: path,
          code: 'not_found',
        },
      });
    }
    return route.fulfill({
      status: 401,
      contentType: 'application/problem+json',
      json: {
        type: '/problems/not_signed_in',
        title: 'Unauthorized',
        status: 401,
        detail: 'Sign in to continue.',
        code: 'not_signed_in',
      },
    });
  });
}

test('a signed-out learner opens a session, signs in and lands back on it', async ({ page }) => {
  await fakeApi(page);

  await page.goto('/sessions/abc-123');

  await expect(page).toHaveURL('/sign-in?next=%2Fsessions%2Fabc-123');
  await expect(page).toHaveTitle('Sign in · ListenUp');

  // The first Tab reaches the skip link.
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();

  await page.getByLabel('Email').fill('learner@example.com');
  await page.getByLabel('Password').fill('correct horse');
  await page.getByLabel('Password').press('Enter');

  await expect(page).toHaveURL('/sessions/abc-123');
  await expect(page).toHaveTitle('Blind · ListenUp');
  const main = page.getByRole('main');
  // Focus moves to the new page's content after the learner's own navigation.
  await expect(main).toBeFocused();
  await expect(main.getByRole('region', { name: 'Plan progress' })).toBeVisible();
  await expect(main.getByRole('region', { name: 'Player' })).toBeVisible();
  await expect(main.getByRole('region', { name: 'Blind' })).toBeVisible();
});

test('the shell fits a 360 px screen without sideways scrolling', async ({ page }) => {
  await fakeApi(page, { signedIn: true });
  await page.setViewportSize({ width: 360, height: 740 });

  for (const path of ['/library', '/library/add', '/sessions/abc-123', '/no-such-page']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});

test('a learner uploads a clip with progress and sees it in the library', async ({ page }) => {
  const items: object[] = [];
  let putBody = 0;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const method = request.method();
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/library/contents') return route.fulfill({ json: { items, next_cursor: null } });
    if (path === '/sessions') return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === '/uploads/usage') {
      return route.fulfill({
        json: { used_bytes: 0, quota_bytes: 2 ** 31, max_file_bytes: 500 * 2 ** 20 },
      });
    }
    if (path === '/uploads' && method === 'POST') {
      return route.fulfill({
        status: 201,
        json: {
          upload_id: 'up-1',
          url: 'http://storage.e2e.test/listenup/users/1/uploads/up-1.mp3?X-Amz-Signature=x',
          method: 'PUT',
          headers: { 'Content-Type': 'audio/mpeg' },
          expires_at: '2030-01-01T00:00:00Z',
        },
      });
    }
    if (path === '/contents' && method === 'POST') {
      const item = {
        id: 'content-1',
        title: 'street-trees-talk',
        source: 'upload',
        status: 'pending',
        duration_ms: null,
        created_at: '2026-10-03T09:00:00Z',
      };
      items.push({ ...item, last_session_status: null });
      return route.fulfill({ status: 201, json: item });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found', detail: path } });
  });
  // Object storage: answers the CORS preflight and takes the PUT.
  await page.route('http://storage.e2e.test/**', async (route) => {
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'PUT',
      'Access-Control-Allow-Headers': 'content-type',
    };
    if (route.request().method() === 'PUT') putBody = route.request().postDataBuffer()?.length ?? 0;
    return route.fulfill({ status: 200, headers: cors, body: '' });
  });

  await page.goto('/library');
  await expect(page.getByRole('heading', { name: 'Add your first clip' })).toBeVisible();
  await page.getByRole('link', { name: 'Upload a file' }).click();
  await expect(page).toHaveTitle('Add a clip · ListenUp');

  await page.locator('input[type="file"]').setInputFiles({
    name: 'street-trees-talk.mp3',
    mimeType: 'audio/mpeg',
    buffer: Buffer.alloc(256 * 1024, 1),
  });

  await expect(page).toHaveURL('/library');
  const clip = page.getByRole('listitem').filter({ hasText: 'street-trees-talk' });
  await expect(clip).toContainText('Processing');
  expect(putBody).toBe(256 * 1024);
});

test('a file of the wrong type is refused before it is sent', async ({ page }) => {
  await fakeApi(page, { signedIn: true });
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/library/add');

  await page.getByRole('button', { name: 'Choose a file' }).focus();
  await page.locator('input[type="file"]').setInputFiles({
    name: 'notes.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF'),
  });

  await expect(page.getByRole('alert')).toContainText("notes.pdf can't be used");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

/** A WAV of `seconds` of a quiet 440 Hz tone, small enough to build in the test. */
function toneWav(seconds: number, rate = 8000): Buffer {
  const samples = seconds * rate;
  const wav = Buffer.alloc(44 + samples * 2);
  wav.write('RIFF', 0);
  wav.writeUInt32LE(36 + samples * 2, 4);
  wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20); // PCM
  wav.writeUInt16LE(1, 22); // mono
  wav.writeUInt32LE(rate, 24);
  wav.writeUInt32LE(rate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write('data', 36);
  wav.writeUInt32LE(samples * 2, 40);
  for (let n = 0; n < samples; n += 1) {
    wav.writeInt16LE(Math.round(4000 * Math.sin((2 * Math.PI * 440 * n) / rate)), 44 + n * 2);
  }
  return wav;
}

/**
 * Stands in for object storage: serves one file and answers range requests with 206,
 * as S3 does. The browser does not route requests it reaches through a redirect, so
 * this is a real server on a free local port, closed after the test.
 */
async function fakeStorage(body: Buffer) {
  const ranges: string[] = [];
  const server = createServer((request, response) => {
    const match = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range ?? '');
    const headers = { 'Content-Type': 'audio/wav', 'Accept-Ranges': 'bytes' };
    if (!match) {
      response.writeHead(200, { ...headers, 'Content-Length': body.length });
      response.end(body);
      return;
    }
    ranges.push(match[0]);
    const start = Number(match[1]);
    const end = match[2] ? Math.min(Number(match[2]), body.length - 1) : body.length - 1;
    response.writeHead(206, {
      ...headers,
      'Content-Length': end - start + 1,
      'Content-Range': `bytes ${start}-${end}/${body.length}`,
    });
    response.end(body.subarray(start, end + 1));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/listenup/users/1/media/media-1/playback.wav?X-Amz-Signature=x`,
    ranges,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

test('a learner opens a ready clip from the library and plays it', async ({ page }) => {
  const clip = {
    id: 'content-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: 3000,
    created_at: '2026-10-03T09:00:00Z',
  };
  const storage = await fakeStorage(toneWav(3));
  try {
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
      if (path === '/health') return route.fulfill({ json: { status: 'ok' } });
      if (path === '/me') return route.fulfill({ json: LEARNER });
      if (path === '/library/contents') {
        return route.fulfill({
          json: { items: [{ ...clip, last_session_status: null }], next_cursor: null },
        });
      }
      if (path === '/contents/content-1') {
        return route.fulfill({
          json: {
            ...clip,
            media_object_id: 'media-1',
            has_video: false,
            keep_video: false,
            error_code: null,
            error_detail: null,
            media_url: '/api/v1/media/media-1',
            peaks_url: '/api/v1/media/media-1/peaks',
          },
        });
      }
      // The API checks ownership, then sends the player to a signed storage URL.
      if (path === '/media/media-1') {
        return route.fulfill({ status: 307, headers: { Location: storage.url } });
      }
      return route.fulfill({ status: 404, json: { code: 'not_found', detail: path } });
    });

    await page.goto('/library');
    await page.getByRole('link', { name: 'Why cities plant street trees', exact: true }).click();

    await expect(page).toHaveURL('/contents/content-1');
    await expect(page).toHaveTitle('Why cities plant street trees · ListenUp');
    await expect(page.getByRole('status')).toHaveText('Ready to play.');
    const player = page.getByLabel('Play Why cities plant street trees');
    await expect(player).toHaveAttribute('controls', '');

    // The player follows the redirect to storage and reads the file's length.
    await expect
      .poll(() => player.evaluate((el: HTMLAudioElement) => el.duration))
      .toBeCloseTo(3, 1);
    // Seeking asks storage for a range instead of the whole file.
    const seeked = await player.evaluate(
      (el: HTMLAudioElement) =>
        new Promise<number>((resolve) => {
          el.addEventListener('seeked', () => resolve(el.currentTime), { once: true });
          el.currentTime = 2;
        }),
    );
    expect(seeked).toBeCloseTo(2, 1);
    expect(storage.ranges.length).toBeGreaterThan(0);

    // The native controls are reachable from the keyboard.
    await player.focus();
    await expect(player).toBeFocused();
  } finally {
    await storage.close();
  }
});
