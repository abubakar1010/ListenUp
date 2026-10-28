import { type Page } from '@playwright/test';
import { expect, test } from './test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
  deletion_grace_days: 7,
  consents_required: [],
};
const PASSAGE = { start_ms: 0, end_ms: 30_000 };

/** A session of Dictation only, open at Dictation. */
const SESSION = {
  id: 's-1',
  content_id: 'clip-1',
  content_title: 'Why cities plant street trees',
  passage: PASSAGE,
  entry: 'dictation',
  status: 'active',
  version: 0,
  steps: [
    { step: 'dictation', position: 1, status: 'open' },
    { step: 'transcript', position: 2, status: 'locked' },
    { step: 'card', position: 3, status: 'locked' },
    { step: 'shadow', position: 4, status: 'locked' },
  ],
  step_count: 4,
  open_step: 'dictation',
  open_position: 1,
  entry_locked: false,
  entry_locked_at: null,
  completed_at: null,
  created_at: '2026-10-03T09:00:00Z',
  updated_at: '2026-10-03T09:00:00Z',
};

/** 35 s of near-silence as an 8 kHz, 8-bit mono WAV, so the browser can really play it. */
function wav(seconds: number): Buffer {
  const rate = 8000;
  const samples = rate * seconds;
  const buffer = Buffer.alloc(44 + samples, 128);
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
  return buffer;
}

const AUDIO = wav(35);

test('reference correction by keyboard updates score and Edited marker at 360px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await fakeApi(page, newServer());
  let edited = false;
  let finishSave!: () => void;
  const saveResponse = new Promise<void>((resolve) => {
    finishSave = resolve;
  });
  const result = () => ({
    id: 'attempt-1',
    session_id: 's-1',
    status: 'submitted',
    scoring_status: 'scored',
    result: {
      accuracy: edited ? 100 : 0,
      counts: {
        correct: edited ? 1 : 0,
        spelling_slip: 0,
        wrong: edited ? 0 : 1,
        missing: 0,
        extra: 0,
      },
      items: [
        {
          index: 0,
          status: edited ? 'correct' : 'wrong',
          word: edited ? 'cap' : 'cat',
          typed: 'cap',
        },
      ],
    },
  });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/sessions/s-1')
      return route.fulfill({
        json: {
          ...SESSION,
          open_step: 'transcript',
          open_position: 2,
          version: 1,
          steps: SESSION.steps.map((step, i) => ({
            ...step,
            status: i === 0 ? 'done' : i === 1 ? 'open' : 'locked',
          })),
        },
      });
    if (path === '/sessions/s-1/dictation/attempt') return route.fulfill({ json: result() });
    if (path === '/dictation/attempts/attempt-1/disputes') {
      expect(request.postDataJSON()).toEqual({ word_index: 0, corrected_text: 'cap' });
      expect(request.headers()['idempotency-key']).toBeTruthy();
      expect(request.headers()['x-csrf-token']).toBeTruthy();
      await saveResponse;
      edited = true;
      return route.fulfill({ json: result() });
    }
    if (path === '/sessions/s-1/transcript')
      return route.fulfill({
        json: {
          session_id: 's-1',
          passage: PASSAGE,
          media_url: '/api/v1/media/media-1',
          lines: [
            {
              index: 0,
              start_ms: 1000,
              end_ms: 1800,
              words: [
                { index: 0, text: edited ? 'cap' : 'cat', start_ms: 1000, end_ms: 1800, edited },
              ],
            },
          ],
        },
      });
    if (path === '/dictation/attempts/attempt-1/marks' || path === '/sessions/s-1/marks')
      return route.fulfill({ json: { marks: [] } });
    return route.fallback();
  });
  await page.goto('/sessions/s-1');
  const opener = page.getByRole('button', { name: 'Correct reference word cat' });
  await opener.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await page.keyboard.press('Tab');
  const input = dialog.getByRole('textbox', { name: 'Corrected text' });
  await expect(input).toBeFocused();
  await input.fill('cap');
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Save correction' })).toBeFocused();
  await page.keyboard.press('Enter');
  try {
    await expect(dialog.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    await expect(dialog).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(dialog).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(dialog).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeVisible();
  } finally {
    finishSave();
  }
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('100%')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Jump to cap, edited' })).toBeVisible();
  await expect(page.getByText('Edited', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Correct reference word cap' })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
});

/** The server's draft, shared by every page of the test, as the real API would hold it. */
interface Server {
  text: string;
  version: number;
  puts: { draft_text: string; draft_version: number }[];
  paths: string[];
}

async function fakeApi(page: Page, server: Server) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    server.paths.push(`${request.method()} ${path}`);
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/me') return route.fulfill({ json: LEARNER });
    if (path === '/sessions/s-1') return route.fulfill({ json: SESSION });
    if (path === '/sessions/s-1/dictation/attempts') {
      return route.fulfill({
        json: {
          id: 'attempt-1',
          session_id: 's-1',
          status: 'active',
          started_at: '2026-10-03T10:00:00Z',
          resumed: true,
          draft_text: server.text,
          draft_version: server.version,
          draft_updated_at: '2026-10-03T10:00:00Z',
          passage: PASSAGE,
          media_url: '/api/v1/media/media-1',
        },
      });
    }
    if (path === '/dictation/attempts/attempt-1/draft') {
      const body = request.postDataJSON() as { draft_text: string; draft_version: number };
      server.puts.push(body);
      if (body.draft_version !== server.version && body.draft_text !== server.text) {
        const status = 409;
        return route.fulfill({
          status,
          contentType: 'application/problem+json',
          json: {
            type: '/problems/draft_conflict',
            title: 'Conflict',
            status,
            detail: 'Your text was changed in another tab or browser.',
            code: 'draft_conflict',
            draft_text: server.text,
            draft_version: server.version,
            updated_at: '2026-10-03T10:50:00Z',
          },
        });
      }
      if (body.draft_text !== server.text) {
        server.text = body.draft_text;
        server.version += 1;
      }
      return route.fulfill({
        json: { draft_version: server.version, updated_at: new Date().toISOString() },
      });
    }
    if (path === '/media/media-1') {
      // Range requests, as storage answers them, so the player can seek (System Design 6.4).
      const range = /bytes=(\d+)-(\d*)/.exec(request.headers()['range'] ?? '');
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
}

function newServer(text = 'So the first thing'): Server {
  return { text, version: 1, puts: [], paths: [] };
}

test('the draft saves itself and comes back after a reload', async ({ page }) => {
  const server = newServer();
  await fakeApi(page, server);
  await page.goto('/sessions/s-1');

  const text = page.getByRole('textbox', { name: 'Your text' });
  await expect(text).toHaveValue('So the first thing');
  await expect(text).toBeFocused();
  await expect(text).toHaveAttribute('spellcheck', 'false');
  await expect(text).toHaveAttribute('autocorrect', 'off');
  await expect(text).toHaveAttribute('autocapitalize', 'off');
  await expect(text).toHaveAttribute('autocomplete', 'off');

  await text.press('End');
  await text.pressSequentially(' you notice is the shade');
  await expect.poll(() => server.puts.length, { timeout: 5000 }).toBe(1);
  expect(server.puts[0]).toEqual({
    draft_text: 'So the first thing you notice is the shade',
    draft_version: 1,
  });
  await expect(page.getByText(/Draft saved \d\d:\d\d/).first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Your text' })).toHaveValue(
    'So the first thing you notice is the shade',
  );
  expect(server.paths.some((path) => /transcript/i.test(path))).toBe(false);
});

test('text typed just before a reload is kept on the device and saved', async ({ page }) => {
  const server = newServer('');
  await fakeApi(page, server);
  await page.goto('/sessions/s-1');
  const text = page.getByRole('textbox', { name: 'Your text' });
  await text.pressSequentially('typed and reloaded at once');

  await page.reload(); // within the 2 s debounce

  await expect(page.getByRole('textbox', { name: 'Your text' })).toHaveValue(
    'typed and reloaded at once',
  );
  await expect.poll(() => server.text).toBe('typed and reloaded at once');
});

test('two tabs do not silently overwrite each other', async ({ context }) => {
  const server = newServer();
  const first = await context.newPage();
  const second = await context.newPage();
  await fakeApi(first, server);
  await fakeApi(second, server);
  await first.goto('/sessions/s-1');
  await second.goto('/sessions/s-1');
  await expect(second.getByRole('textbox', { name: 'Your text' })).toHaveValue(
    'So the first thing',
  );

  const one = first.getByRole('textbox', { name: 'Your text' });
  await one.fill('Typed in the first tab');
  await one.blur();
  await expect.poll(() => server.text).toBe('Typed in the first tab');

  const two = second.getByRole('textbox', { name: 'Your text' });
  await two.fill('Typed in the second tab');
  await two.blur();

  const panel = second.getByRole('alert');
  await expect(panel).toContainText('Your text was changed in another tab');
  expect(server.text).toBe('Typed in the first tab');

  await panel.getByRole('button', { name: 'Use the other version' }).click();
  await expect(two).toHaveValue('Typed in the first tab');
});

test('the player plays only the passage and stops at its end', async ({ page }) => {
  await fakeApi(page, newServer());
  await page.goto('/sessions/s-1');
  const player = page.getByRole('region', { name: 'Player' });
  await expect(player.getByText('00:00 / 00:30')).toBeVisible();
  await expect(player.getByRole('button', { name: 'Play', exact: true })).toBeEnabled();

  await player.getByRole('slider', { name: 'Seek' }).fill('28000');
  await player.getByRole('combobox', { name: 'Speed' }).selectOption('0.75');
  await player.getByRole('button', { name: 'Play', exact: true }).click();

  await expect(player.getByText('00:30 / 00:30')).toBeVisible({ timeout: 10_000 });
  await expect(player.getByRole('button', { name: 'Play', exact: true })).toBeVisible();

  await player.getByRole('button', { name: 'Replay segment' }).click();
  await expect(player.getByText(/^1 replay$/)).toBeVisible();
  await expect(player.getByRole('button', { name: 'Pause' })).toBeVisible();
});

test('the seek slider is 44 px tall to touch at 360 px and 24 px on desktop (UX-15)', async ({
  page,
}) => {
  await fakeApi(page, newServer());
  for (const [width, min] of [
    [360, 44],
    [1280, 24],
  ]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/sessions/s-1');
    const seek = page.getByRole('slider', { name: 'Seek' });
    await expect(seek).toBeVisible();
    expect((await seek.boundingBox())!.height, `at ${width} px`).toBeGreaterThanOrEqual(min);
  }
});

test('submitting shows the waiting message, then the diff with labels, at 360 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  const server = newServer();
  await fakeApi(page, server);
  let state: 'open' | 'waiting' | 'scored' = 'open';
  const view = (scoring: string, result: unknown) => ({
    id: 'attempt-1',
    session_id: 's-1',
    status: 'submitted',
    scoring_status: scoring,
    result,
  });
  // Later routes win: the submit moves the plan on to Transcript, and the score lands later.
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/sessions/s-1' && state !== 'open') {
      return route.fulfill({
        json: {
          ...SESSION,
          version: 1,
          open_step: 'transcript',
          open_position: 2,
          steps: SESSION.steps.map((s, i) => ({
            ...s,
            status: i === 0 ? 'done' : i === 1 ? 'open' : 'locked',
          })),
        },
      });
    }
    if (path === '/dictation/attempts/attempt-1/submit') {
      state = 'waiting';
      return route.fulfill({
        status: 202,
        json: {
          attempt_id: 'attempt-1',
          status: 'submitted',
          scoring_status: 'waiting_transcript',
        },
      });
    }
    if (path === '/sessions/s-1/dictation/attempt') {
      return route.fulfill({
        json:
          state === 'scored'
            ? view('scored', {
                accuracy: 50,
                counts: { correct: 1, spelling_slip: 0, wrong: 1, missing: 0, extra: 0 },
                items: [
                  { index: 0, status: 'correct', word: 'Cities', typed: 'Cities' },
                  { index: 1, status: 'wrong', word: 'plant', typed: 'plan' },
                ],
              })
            : view('waiting_transcript', null),
      });
    }
    if (path === '/dictation/attempts/attempt-1/marks')
      return route.fulfill({ json: { marks: [] } });
    return route.fallback();
  });
  await page.goto('/sessions/s-1');

  await page.getByRole('button', { name: 'Submit for scoring' }).click();
  // Submitting asks once (UX-27); the safe action has focus and sits first on mobile.
  const dialog = page.getByRole('dialog', { name: 'Submit your Dictation?' });
  await expect(dialog).toContainText('You typed 4 words.');
  const keep = dialog.getByRole('button', { name: 'Keep typing' });
  const send = dialog.getByRole('button', { name: 'Submit' });
  await expect(keep).toBeFocused();
  expect((await keep.boundingBox())!.y).toBeLessThan((await send.boundingBox())!.y);
  await send.click();

  await expect(page.getByText(/Scoring when the transcript is ready/)).toBeVisible();
  // No diff, so no reference text, before the score.
  await expect(page.getByRole('list', { name: 'Word by word' })).toHaveCount(0);
  state = 'scored';
  await page.reload();
  await expect(page.getByText('50%')).toBeVisible();
  const diff = page.getByRole('list', { name: 'Word by word' });
  await expect(diff).toContainText('Wrong');
  await expect(diff).toContainText('you typed plan');
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(360);
});

test('missed words go to the mark list by keyboard alone (FR-DI-6, #55)', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await fakeApi(page, newServer());
  const marks: { id: string; word_from: number; word_to: number }[] = [];
  const posted: unknown[] = [];
  const answer = (m: { id: string; word_from: number; word_to: number }) => ({
    ...m,
    at_ms: 1000 * (m.word_from + 1),
    source: 'dictation',
    status: 'suggested',
  });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/sessions/s-1') {
      return route.fulfill({
        json: {
          ...SESSION,
          version: 1,
          open_step: 'transcript',
          open_position: 2,
          steps: SESSION.steps.map((s, i) => ({
            ...s,
            status: i === 0 ? 'done' : i === 1 ? 'open' : 'locked',
          })),
        },
      });
    }
    if (path === '/sessions/s-1/dictation/attempt') {
      return route.fulfill({
        json: {
          id: 'attempt-1',
          session_id: 's-1',
          status: 'submitted',
          scoring_status: 'scored',
          result: {
            accuracy: 40,
            counts: { correct: 2, spelling_slip: 0, wrong: 1, missing: 2, extra: 0 },
            items: [
              { index: 0, status: 'correct', word: 'Cities', typed: 'Cities' },
              { index: 1, status: 'missing', word: 'plant', typed: '' },
              { index: 2, status: 'correct', word: 'street', typed: 'street' },
              { index: 3, status: 'missing', word: 'trees', typed: '' },
              { index: 4, status: 'wrong', word: 'to', typed: 'two' },
            ],
          },
        },
      });
    }
    if (path === '/dictation/attempts/attempt-1/marks') {
      if (request.method() === 'GET') return route.fulfill({ json: { marks: marks.map(answer) } });
      const body = request.postDataJSON() as { marks: typeof marks };
      posted.push(body);
      marks.push(...body.marks);
      return route.fulfill({ json: { marks: body.marks.map(answer) } });
    }
    return route.fallback();
  });
  await page.goto('/sessions/s-1');

  const addAll = page.getByRole('button', { name: 'Add all' });
  await addAll.focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Add “plant” to marks' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: '“plant” added to marks' })).toBeFocused();

  await addAll.focus();
  await page.keyboard.press('Space');

  await expect(page.getByRole('button', { name: 'All added' })).toBeVisible();
  await expect(page.getByRole('button', { name: '“trees to” added to marks' })).toBeVisible();
  expect(posted).toEqual([
    { marks: [{ id: expect.any(String), word_from: 1, word_to: 1 }] },
    { marks: [{ id: expect.any(String), word_from: 3, word_to: 4 }] },
  ]);
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(360);
});
