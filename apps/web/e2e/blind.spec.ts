import { expect, test, type Page, type Route } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
  deletion_grace_days: 7,
};
const PASSAGE = { start_ms: 0, end_ms: 30_000 };

/** A silent WAV, 8 kHz mono 8-bit, so the browser really plays something. */
function silentWav(seconds: number): Buffer {
  const samples = 8_000 * seconds;
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + samples, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(8_000, 24);
  header.writeUInt32LE(8_000, 28);
  header.writeUInt16LE(1, 32);
  header.writeUInt16LE(8, 34);
  header.write('data', 36);
  header.writeUInt32LE(samples, 40);
  return Buffer.concat([header, Buffer.alloc(samples, 128)]);
}

function session(open: 'blind' | 'transcript') {
  const steps = ['blind', 'transcript', 'card', 'shadow'].map((step, index) => ({
    step,
    position: index + 1,
    status: step === open ? 'open' : index === 0 ? 'done' : 'locked',
  }));
  return {
    id: 's-1',
    content_id: 'clip-1',
    content_title: 'Why cities plant street trees',
    passage: PASSAGE,
    entry: 'blind',
    status: 'active',
    version: open === 'blind' ? 0 : 1,
    steps,
    step_count: 4,
    open_step: open,
    open_position: open === 'blind' ? 1 : 2,
    entry_locked: open !== 'blind',
    entry_locked_at: null,
    completed_at: null,
    created_at: '2026-10-03T09:00:00Z',
    updated_at: '2026-10-03T09:00:00Z',
  };
}

function attempt(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a-1',
    session_id: 's-1',
    status: 'active',
    void_reason: null,
    started_at: '2026-10-03T10:00:00Z',
    finished_at: null,
    passage_start_ms: PASSAGE.start_ms,
    passage_end_ms: PASSAGE.end_ms,
    position_ms: 0,
    resume_count: 0,
    resume_stop_ms: null,
    listen_complete: false,
    gist_text: null,
    ...overrides,
  };
}

function problem(route: Route, status: number, code: string, detail: string) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code },
  });
}

/** The API, answered in the test: a Blind session and its attempts. */
async function fakeApi(page: Page, { complete = false } = {}) {
  const posts: { path: string; body: unknown; headers: Record<string, string> }[] = [];
  let open: 'blind' | 'transcript' = 'blind';
  let current: ReturnType<typeof attempt> | null = complete
    ? attempt({ position_ms: PASSAGE.end_ms, listen_complete: true })
    : null;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const method = request.method();
    if (method === 'POST') {
      posts.push({ path, body: request.postDataJSON(), headers: request.headers() });
    }
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/sessions/s-1') return route.fulfill({ json: session(open) });
    if (path === '/sessions/s-1/blind') {
      return route.fulfill({
        json: {
          session_id: 's-1',
          passage_start_ms: PASSAGE.start_ms,
          passage_end_ms: PASSAGE.end_ms,
          step_status: open === 'blind' ? 'open' : 'done',
          attempt: current,
        },
      });
    }
    if (path === '/sessions/s-1/blind/attempts') {
      current = attempt();
      return route.fulfill({
        status: 201,
        json: {
          attempt: current,
          media_url: '/api/v1/blind/attempts/a-1/media/token',
          heartbeat_interval_ms: 5_000,
          resume_delay_ms: 3_000,
        },
      });
    }
    if (path === '/blind/attempts/a-1/media/token') {
      return route.fulfill({ contentType: 'audio/wav', body: silentWav(31) });
    }
    if (path === '/blind/attempts/a-1/heartbeat') {
      return route.fulfill({
        json: { action: 'continue', attempt: current, resume_from_ms: null, resume_delay_ms: 3000 },
      });
    }
    if (path === '/blind/attempts/a-1/void') {
      const { reason } = request.postDataJSON() as { reason: string };
      current = attempt({ status: 'voided', void_reason: reason, position_ms: 2_000 });
      return route.fulfill({ json: current });
    }
    if (path === '/blind/attempts/a-1/gist') {
      const { text } = request.postDataJSON() as { text: string };
      if (text.split('. ').length < 3) {
        return problem(route, 422, 'gist_too_short', '2 of 3 sentences.');
      }
      open = 'transcript';
      current = attempt({ status: 'submitted', gist_text: text, listen_complete: true });
      return route.fulfill({
        status: 201,
        json: { attempt: current, open_step: 'transcript', session_version: 1 },
      });
    }
    return problem(route, 404, 'not_found', path);
  });
  return { posts };
}

test('Blind plays with Start and volume only, and leaving ends the attempt', async ({ page }) => {
  const { posts } = await fakeApi(page);
  await page.goto('/sessions/s-1');

  await expect(page.getByRole('heading', { name: 'Before you start' })).toBeVisible();
  const player = page.getByRole('group', { name: 'Blind player' });
  await expect(player.getByRole('button')).toHaveText(['Start listening']);
  await expect(player.getByRole('slider', { name: 'Volume' })).toBeVisible();

  await player.getByRole('button', { name: 'Start listening' }).click();
  await expect(player.getByText('Listening', { exact: true })).toBeVisible();
  await expect(player.getByText(/^00:0[1-9] \/ 00:30$/)).toBeVisible();
  // No control to pause, seek, rewind or change speed, and no way back while listening.
  await expect(player.getByRole('button')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Library' })).toHaveCount(0);

  // Keys and media keys that pause or seek elsewhere do nothing here.
  for (const key of ['Space', 'k', 'ArrowLeft', 'ArrowRight', 'j', 'l', 'MediaPlayPause']) {
    await page.keyboard.press(key);
  }
  const state = await page.evaluate(() => {
    const audio = document.querySelector('audio')!;
    return { paused: audio.paused, rate: audio.playbackRate, controls: audio.controls };
  });
  expect(state).toEqual({ paused: false, rate: 1, controls: false });
  await page.waitForTimeout(500);
  expect(posts.filter((p) => p.path.endsWith('/void'))).toHaveLength(0);

  // The page goes away mid-listen: the server hears about it.
  const voided = page.waitForRequest((r) => r.url().endsWith('/blind/attempts/a-1/void'));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
  expect((await voided).postDataJSON()).toEqual({ reason: 'left_page' });

  await expect(page.getByRole('alert')).toContainText('Your Blind attempt ended');
  await expect(page.getByRole('alert')).toContainText('You left the page at 00:02.');
  await expect(page.getByRole('button', { name: 'Start listening' })).toBeVisible();
});

test('after the whole passage the gist needs three sentences', async ({ page }) => {
  const { posts } = await fakeApi(page, { complete: true });
  await page.goto('/sessions/s-1');

  const gist = page.getByRole('textbox', { name: 'Your gist' });
  await expect(gist).toBeFocused();
  await gist.fill('Cities plant trees on streets. Shade cools the air.');
  await expect(page.getByText('2 of 3 sentences. Write one more.', { exact: true })).toBeVisible();
  // Submit stays focusable while it is not ready, and says what is missing.
  await page.getByRole('button', { name: 'Submit gist' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alert')).toHaveText(
    '2 of 3 sentences. Write one more, then submit.',
  );
  expect(posts.filter((p) => p.path.endsWith('/gist'))).toHaveLength(0);

  await gist.fill('Cities plant trees on streets. Shade cools the air. Roots can break pipes.');
  await page.getByRole('button', { name: 'Submit gist' }).click();

  await expect(page.getByText('Step 2 of 4')).toBeVisible();
  const submitted = posts.filter((p) => p.path.endsWith('/gist'));
  expect(submitted).toHaveLength(1);
  expect(submitted[0].headers['idempotency-key']).toBe('gist-a-1');
});
