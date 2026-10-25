import { expect, test, type BrowserContext, type Page } from '@playwright/test';

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

test('AT-8: a second browser signs in and resumes Transcript with saved marks', async ({
  browser,
}) => {
  const learner = {
    id: 'learner-50',
    email: 'resume@example.com',
    display_name: null,
    email_verified: false,
    deletion_grace_days: 7,
    consents_required: [],
  };
  // Only this fake server state is shared; neither browser gets the other's storage.
  const marks: Record<string, unknown>[] = [];
  let signIns = 0;
  async function server(context: BrowserContext) {
    let signedIn = false;
    await context.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/api/v1', '');
      if (path === '/health')
        return route.fulfill({
          json: { status: 'ok' },
          headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
        });
      if (path === '/auth/login' && request.method() === 'POST') {
        expect(request.postDataJSON()).toEqual({
          email: learner.email,
          password: 'correct horse battery',
        });
        signedIn = true;
        signIns += 1;
        return route.fulfill({ json: learner });
      }
      if (!signedIn) return route.fulfill({ status: 401, json: { code: 'not_signed_in' } });
      if (path === '/me') return route.fulfill({ json: learner });
      if (path === '/library/contents')
        return route.fulfill({
          json: {
            items: [
              {
                id: SESSION.content_id,
                title: SESSION.content_title,
                source: 'upload',
                status: 'playable',
                duration_ms: 35000,
                created_at: SESSION.created_at,
                last_session_status: 'active',
              },
            ],
            next_cursor: null,
          },
        });
      if (path === '/sessions')
        return route.fulfill({ json: { items: [SESSION], next_cursor: null } });
      if (path === '/sessions/s-57') return route.fulfill({ json: SESSION });
      if (path === '/sessions/s-57/dictation/attempt')
        return route.fulfill({ status: 404, json: { code: 'attempt_not_found' } });
      if (path === '/sessions/s-57/transcript')
        return route.fulfill({
          json: {
            session_id: SESSION.id,
            passage: PASSAGE,
            media_url: '/api/v1/media/m-57',
            lines: [
              {
                index: 0,
                start_ms: 0,
                end_ms: 12000,
                words: [
                  { index: 0, text: 'Hello.', start_ms: 0, end_ms: 1000 },
                  { index: 1, text: 'Again.', start_ms: 10000, end_ms: 12000 },
                ],
              },
            ],
          },
        });
      if (path === '/sessions/s-57/marks' && request.method() === 'GET')
        return route.fulfill({ json: { marks } });
      if (path === '/sessions/s-57/marks' && request.method() === 'POST') {
        const body = request.postDataJSON() as { id: string; word_from: number };
        const existing = marks.find((mark) => mark['id'] === body.id);
        const mark = existing ?? {
          ...body,
          session_id: SESSION.id,
          at_ms: body.word_from === 0 ? 0 : 10000,
          note: null,
          source: 'manual',
          status: 'confirmed',
          created_at: '2026-10-23T00:00:00Z',
        };
        if (!existing) marks.push(mark);
        return route.fulfill({ status: existing ? 200 : 201, json: mark });
      }
      if (path.startsWith('/sessions/s-57/marks/') && request.method() === 'PATCH') {
        const mark = marks.find((item) => path.endsWith(`/${String(item['id'])}`));
        expect(mark).toBeDefined();
        Object.assign(mark!, request.postDataJSON());
        return route.fulfill({ json: mark });
      }
      if (path === '/media/m-57') return route.fulfill({ contentType: 'audio/wav', body: AUDIO });
      if (path === '/events')
        return route.fulfill({ contentType: 'text/event-stream', body: ': connected\n\n' });
      throw new Error(`Unexpected API request: ${request.method()} ${path}`);
    });
  }
  async function signInAndResume(page: Page) {
    await page.goto('/library');
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
    await page.getByLabel('Email', { exact: true }).fill(learner.email);
    await page.getByLabel('Password', { exact: true }).fill('correct horse battery');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    const plans = page.getByRole('region', { name: 'Your plans' });
    await expect(plans).toContainText('Step 2 of 4 · Transcript');
    await plans.getByRole('link', { name: 'Resume Transcript practice' }).click();
    await expect(page).toHaveURL('/sessions/s-57');
    await expect(
      page.getByRole('heading', { name: 'Transcript: Transcript practice' }),
    ).toBeVisible();
    await expect(
      page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem').nth(1),
    ).toHaveAttribute('aria-current', 'step');
  }

  const first = await browser.newContext();
  try {
    await server(first);
    const page = await first.newPage();
    await signInAndResume(page);
    const hello = page.getByRole('button', { name: 'Jump to Hello.', exact: true });
    await hello.focus();
    await page.keyboard.press('m');
    await expect(hello).toHaveAccessibleDescription('Marked');
    await page.getByLabel('Note (optional)').fill('linking sound');
    const again = page.getByRole('button', { name: 'Jump to Again.', exact: true });
    await again.focus(); // blur saves the note
    await page.keyboard.press('m');
    await expect(page.getByText('2 marks', { exact: true })).toBeVisible();
    await expect.poll(() => marks.map((mark) => mark['note'])).toEqual(['linking sound', null]);
    await expect(page.getByRole('region', { name: 'Mark words' })).toContainText('Marks saved');
  } finally {
    await first.close();
  }

  const saved = structuredClone(marks);
  const second = await browser.newContext();
  try {
    expect(await second.storageState()).toEqual({ cookies: [], origins: [] });
    await server(second);
    const page = await second.newPage();
    await signInAndResume(page);
    await expect(
      page.getByRole('button', { name: 'Jump to Hello.', exact: true }),
    ).toHaveAccessibleDescription('Marked');
    await expect(
      page.getByRole('button', { name: 'Jump to Again.', exact: true }),
    ).toHaveAccessibleDescription('Marked');
    await expect(page.getByText('2 marks', { exact: true })).toBeVisible();
    const list = page.getByRole('list', { name: 'Your marks' });
    await expect(list.getByRole('listitem')).toHaveCount(2);
    await expect(list).toContainText('linking sound');
    expect(marks).toEqual(saved);
    expect(signIns).toBe(2);
  } finally {
    await second.close();
  }
});

test('transcript_keyboard_controls_at_360px', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  const marks: Record<string, unknown>[] = [];
  let session = SESSION;
  let completionRequests = 0;
  let releaseMarkSave!: () => void;
  const markSaveGate = new Promise<void>((resolve) => {
    releaseMarkSave = resolve;
  });
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
          consents_required: [],
        },
      });
    if (path === '/sessions/s-57') return route.fulfill({ json: session });
    // Completing Transcript now mounts the real Card screen (#72).
    if (path === '/cards')
      return route.fulfill({ json: { cards: [], remaining: 2, next_cursor: null } });
    if (path === '/sessions/s-57/transcript/complete' && req.method() === 'POST') {
      completionRequests += 1;
      expect(req.headers()['idempotency-key']).toBe('transcript-s-57');
      session = {
        ...SESSION,
        version: 2,
        open_step: 'card',
        open_position: 3,
        steps: SESSION.steps.map((step) => ({
          ...step,
          status: step.step === 'transcript' ? 'done' : step.step === 'card' ? 'open' : step.status,
        })),
      };
      return route.fulfill({ status: 204 });
    }
    if (path === '/sessions/s-57/dictation/attempt')
      return route.fulfill({ status: 404, json: { code: 'attempt_not_found' } });
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
    // A server that keeps the marks it is sent (#58).
    if (path === '/sessions/s-57/marks' && req.method() === 'POST') {
      await markSaveGate;
      const body = req.postDataJSON() as { id: string; word_from: number; word_to: number };
      const mark = {
        ...body,
        session_id: 's-57',
        at_ms: body.word_from === 0 ? 0 : 10000,
        note: null,
        source: 'manual',
        status: 'confirmed',
        created_at: '2026-10-19T00:00:00Z',
      };
      const existing = marks.find((item) => item['id'] === body.id);
      if (!existing) marks.push(mark);
      return route.fulfill({ status: existing ? 200 : 201, json: existing ?? mark });
    }
    if (req.method() === 'PATCH' && /^\/sessions\/s-57\/marks\/[^/]+$/.test(path)) {
      const mark = marks.find((m) => path.endsWith(`/${String(m['id'])}`));
      if (!mark) return route.fulfill({ status: 404, json: { code: 'mark_not_found' } });
      mark['note'] = (req.postDataJSON() as { note: string | null }).note;
      return route.fulfill({ json: mark });
    }
    if (req.method() === 'DELETE' && /^\/sessions\/s-57\/marks\/[^/]+$/.test(path)) {
      const index = marks.findIndex((m) => path.endsWith(`/${String(m['id'])}`));
      if (index < 0) return route.fulfill({ status: 404, json: { code: 'mark_not_found' } });
      marks.splice(index, 1);
      return route.fulfill({ status: 204 });
    }
    if (path === '/sessions/s-57/marks') return route.fulfill({ json: { marks } });
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
  await expect(page.getByRole('button', { name: 'Jump to Hello., edited' })).toContainText(
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

  // Mark a phrase by keyboard (#58, UI-4): arrows move, Shift+arrow selects, M marks.
  const first = page.getByRole('button', { name: 'Jump to Hello., edited' });
  await first.focus();
  await page.keyboard.press('ArrowRight');
  await expect(second).toBeFocused();
  await page.keyboard.press('Shift+ArrowLeft');
  await page.keyboard.press('m');
  await expect(first).toHaveAccessibleDescription('Marked');
  await expect(second).toHaveAccessibleDescription('Marked');
  const panel = page.getByRole('region', { name: 'Mark words' });
  await expect(panel).toContainText('“Hello. Again.”');
  // UX-10: pending saves keep Finish in the native Tab order and explain the block.
  const waitingFinish = page.getByRole('button', { name: 'Finish Transcript', exact: true });
  await second.focus();
  await page.keyboard.press('Tab');
  await expect(waitingFinish).toBeFocused();
  await expect(waitingFinish).toHaveAttribute('aria-disabled', 'true');
  await expect(waitingFinish).toHaveAccessibleDescription(
    'Wait for your marks to save before finishing.',
  );
  await page.keyboard.press('Enter');
  await expect(page.getByText('Wait for your marks to save before finishing.')).toBeFocused();
  expect(completionRequests).toBe(0);
  releaseMarkSave();
  await expect(panel).toContainText('Marks saved', { timeout: 5000 });
  expect(marks).toMatchObject([{ word_from: 0, word_to: 1 }]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // With the note editor open the panel is at its tallest at 360 px, so it scrolls with the
  // page instead of floating over the transcript.
  await page.getByLabel('Note (optional)').fill('sounds like one word');
  await expect(panel).toHaveAttribute('data-sticky', 'false');
  // While words are chosen it sticks below the practice header, never over it.
  await page.keyboard.press('Escape'); // focus is still in the note field: move back to a word
  await first.focus();
  await page.keyboard.press('Escape');
  await expect(panel).toHaveAttribute('data-sticky', 'true');
  await page.evaluate(() => {
    // Room to scroll inside the section the panel sticks in (padding would not count).
    const spacer = document.createElement('div');
    spacer.style.height = '3000px';
    document.querySelector('[data-slot="work"]')!.append(spacer);
    window.scrollTo(0, 1200);
  });
  const header = await page.locator('header').first().boundingBox();
  const stuck = await panel.boundingBox();
  expect(stuck!.y).toBeGreaterThanOrEqual(header!.y + header!.height - 1);
  expect(stuck!.y).toBeLessThan(header!.y + header!.height + 24); // it did stick
  await page.evaluate(() => window.scrollTo(0, 0));
  // The saved mark is there again after a reload.
  await page.reload();
  await expect(page.getByRole('button', { name: 'Jump to Again.' })).toHaveAccessibleDescription(
    'Marked',
  );
  // #60 / AT-4: activate the list's native button by keyboard against real media.
  await expect(page.getByText('1 mark', { exact: true })).toBeVisible();
  const list = page.getByRole('list', { name: 'Your marks' });
  const row = list.getByRole('button', { name: /Play mark/ });
  await page.getByRole('slider', { name: 'Seek' }).fill('20000');
  await row.focus();
  await page.keyboard.press('Enter');
  await expect
    .poll(() => page.locator('audio').evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeLessThan(2);
  await expect(first).toHaveClass(/outline-mark-strong/);
  await expect(second).toHaveClass(/outline-mark-strong/);
  await page.keyboard.press('e');
  await expect(page.getByRole('textbox', { name: 'Note (optional)' })).toBeFocused();
  await page.getByRole('textbox', { name: 'Note (optional)' }).fill('x'.repeat(500));
  await row.focus(); // blur saves the long note
  await expect(list).toContainText('x'.repeat(500));
  await page.keyboard.press('Delete');
  await expect(page.getByText('0 marks', { exact: true })).toBeVisible();
  await expect(first).toBeFocused();
  const undo = page.getByRole('button', { name: 'Undo', exact: true });
  await undo.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('1 mark', { exact: true })).toBeVisible();
  await expect(list).toContainText('x'.repeat(500));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const finish = page.getByRole('button', { name: 'Finish Transcript', exact: true });
  await expect(finish).toBeEnabled({ timeout: 5000 });
  await finish.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Card: Transcript practice' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Skip Card', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('dictation_marks_confirm_and_remove_with_reload_and_noncolour_cues_at_360px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  const marks = [
    {
      id: 'd-59',
      session_id: SESSION.id,
      word_from: 0,
      word_to: 0,
      at_ms: 0,
      note: 'linking',
      source: 'dictation',
      status: 'suggested',
      created_at: '2026-10-23T00:00:00Z',
    },
    {
      id: 'm-59',
      session_id: SESSION.id,
      word_from: 1,
      word_to: 1,
      at_ms: 10000,
      note: null,
      source: 'manual',
      status: 'confirmed',
      created_at: '2026-10-23T00:00:00Z',
    },
  ];
  let confirmations = 0;
  let removals = 0;
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    if (path === '/me')
      return route.fulfill({
        json: {
          id: 'learner-59',
          email: 'test@example.com',
          display_name: null,
          email_verified: false,
          deletion_grace_days: 7,
          consents_required: [],
        },
      });
    if (path === `/sessions/${SESSION.id}`) return route.fulfill({ json: SESSION });
    if (path.endsWith('/dictation/attempt'))
      return route.fulfill({ status: 404, json: { code: 'attempt_not_found' } });
    if (path.endsWith('/transcript'))
      return route.fulfill({
        json: {
          session_id: SESSION.id,
          passage: PASSAGE,
          media_url: '/api/v1/media/m-59',
          lines: [
            {
              index: 0,
              start_ms: 0,
              end_ms: 12000,
              words: [
                { index: 0, text: 'Hello.', start_ms: 0, end_ms: 1000 },
                { index: 1, text: 'Again.', start_ms: 10000, end_ms: 12000 },
              ],
            },
          ],
        },
      });
    if (path.endsWith('/marks/d-59/status')) {
      expect(request.method()).toBe('PUT');
      expect(request.postDataJSON()).toEqual({ status: 'confirmed' });
      confirmations += 1;
      if (confirmations === 1) return route.abort('internetdisconnected');
      marks[0]!.status = 'confirmed';
      return route.fulfill({ json: marks[0] });
    }
    if (path.endsWith('/marks/d-59') && request.method() === 'DELETE') {
      removals += 1;
      if (removals === 1) return route.abort('internetdisconnected');
      marks.splice(0, 1);
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/marks')) return route.fulfill({ json: { marks } });
    if (path === '/events')
      return route.fulfill({ contentType: 'text/event-stream', body: ': connected\n\n' });
    if (path === '/media/m-59') return route.fulfill({ contentType: 'audio/wav', body: AUDIO });
    return route.fulfill({ json: { status: 'ok' } });
  });
  await page.goto(`/sessions/${SESSION.id}`);
  const word = page.getByRole('button', { name: 'Jump to Hello.' });
  await expect(word).toHaveAccessibleDescription('Marked from Dictation, to confirm');
  await expect(word).toHaveClass(/border-dashed/);
  const list = page.getByRole('list', { name: 'Your marks' });
  await expect(list.getByText('Your mark', { exact: true })).toBeVisible();
  await expect(page.getByText('2 marks', { exact: true })).toBeVisible();
  await list.getByRole('button', { name: 'Confirm mark Hello.' }).focus();
  await page.keyboard.press('Enter');
  await expect(list.getByRole('button', { name: 'Play mark 00:00 · Hello.' })).toBeFocused();
  await expect.poll(() => confirmations).toBe(1);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('listenup:marks:s-57')), { timeout: 1000 })
    .toContain('confirmed');
  // The first save lost its connection: reload must retain and retry confirmation.
  await page.reload();
  await expect(word).toHaveAccessibleDescription('Marked from Dictation');
  await expect(word).toHaveClass(/border-solid/);
  await expect(page.getByRole('region', { name: 'Mark words' })).toContainText('Marks saved');
  await expect(page.getByText('2 marks', { exact: true })).toBeVisible();
  await list.getByRole('button', { name: 'Remove mark Hello.' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('1 mark', { exact: true })).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('listenup:marks:s-57')), { timeout: 1000 })
    .toContain('delete');
  await expect.poll(() => removals).toBe(1);
  await page.reload();
  await expect(word).not.toHaveAccessibleDescription(/Dictation/);
  await expect(page.getByRole('region', { name: 'Mark words' })).toContainText('Marks saved');
  await expect(page.getByText('1 mark', { exact: true })).toBeVisible();
  // The Dictation mark is gone from the server; only the learner's own mark is left.
  expect(marks.map((mark) => mark.id)).toEqual(['m-59']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
