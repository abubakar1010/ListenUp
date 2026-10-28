import { type Page } from '@playwright/test';
import { expect, test } from './test';
import { sessionFixture } from '../src/features/session/fixtures';

/** Hold a real SSE reply until the learner has edited the current step. */
async function holdGradeReady(page: Page) {
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        this.addEventListener('grade.ready', (event) => {
          document.documentElement.dataset.gradeReady = (event as MessageEvent).lastEventId;
        });
      }
    };
  });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route('**/api/v1/events', async (route) => {
    await gate;
    await route.fulfill({
      contentType: 'text/event-stream',
      body: 'retry: 60000\n\nid: recovery-ready\nevent: grade.ready\ndata: {"resource_id":"gist-70"}\n\n',
    });
  });
  return release;
}

for (const step of ['dictation', 'transcript'] as const) {
  test(`late grade.ready preserves ${step === 'dictation' ? 'the active Dictation draft' : 'Transcript marks and notes'}`, async ({
    page,
  }) => {
    const release = await holdGradeReady(page);
    const session = sessionFixture({
      id: 's-70',
      entry: 'both',
      done: step === 'dictation' ? 1 : 2,
      passage: { start_ms: 0, end_ms: 30_000 },
    });
    let ready = false;
    let sessionReads = 0;
    let starts = 0;
    const mutations: string[] = [];
    let saveDraft!: () => void;
    const draftGate = new Promise<void>((resolve) => (saveDraft = resolve));
    const mark = {
      id: 'mark-70',
      session_id: session.id,
      word_from: 0,
      word_to: 0,
      at_ms: 0,
      note: 'Keep this listening note',
      source: 'manual',
      status: 'confirmed',
      created_at: '2026-10-26T00:00:00Z',
    };
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/api/v1', '');
      if (path === '/events') return route.fallback();
      if (request.method() !== 'GET') mutations.push(`${request.method()} ${path}`);
      if (path === '/health')
        return route.fulfill({
          json: { status: 'ok' },
          headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
        });
      if (path === '/me')
        return route.fulfill({
          json: {
            id: 'learner-70',
            email: 'learner@example.com',
            display_name: null,
            email_verified: false,
            deletion_grace_days: 7,
            consents_required: [],
          },
        });
      if (path === '/sessions/s-70') {
        sessionReads++;
        return route.fulfill({ json: session });
      }
      if (path === '/sessions/s-70/blind')
        return route.fulfill({
          json: { attempt: { id: 'gist-70', status: 'submitted' } },
        });
      if (path === '/gists/gist-70/grade')
        return route.fulfill({
          json: ready
            ? {
                status: 'ready',
                gist: 'A saved gist.',
                overall: 80,
                level: 'good',
                feedback: 'You caught the main idea. Read the detail.',
                captured_count: 1,
                total_count: 2,
              }
            : { status: 'delayed', gist: 'A saved gist.' },
        });
      if (path === '/sessions/s-70/transcript')
        return route.fulfill({
          json: {
            session_id: session.id,
            passage: session.passage,
            media_url: '/api/v1/media/test',
            lines: [
              {
                index: 0,
                start_ms: 0,
                end_ms: 1000,
                words: [{ index: 0, text: 'Cities', start_ms: 0, end_ms: 1000 }],
              },
            ],
          },
        });
      if (path === '/sessions/s-70/marks') return route.fulfill({ json: { marks: [mark] } });
      if (path === '/sessions/s-70/dictation/attempts') {
        starts++;
        return route.fulfill({
          json: {
            id: 'dictation-70',
            session_id: session.id,
            status: 'active',
            resumed: true,
            started_at: '2026-10-26T00:00:00Z',
            draft_text: 'Previously saved draft',
            draft_version: 1,
            draft_updated_at: '2026-10-26T00:00:00Z',
            passage: session.passage,
            media_url: '/api/v1/media/test',
          },
        });
      }
      if (path === '/dictation/attempts/dictation-70/draft') {
        await draftGate;
        return route.fulfill({ json: { draft_version: 2, updated_at: '2026-10-26T00:01:00Z' } });
      }
      return route.fulfill({ status: 404, json: { code: 'not_found' } });
    });
    await page.goto('/sessions/s-70');
    const focus =
      step === 'dictation'
        ? page.getByRole('textbox', { name: 'Your text' })
        : page.getByRole('button', { name: 'Jump to Cities' });
    if (step === 'dictation') {
      await expect(focus).toHaveValue('Previously saved draft');
      await focus.fill('My active draft must survive late feedback');
    } else {
      await expect(focus).toHaveAccessibleDescription('Marked');
      await expect(page.getByText(mark.note, { exact: true })).toBeVisible();
      await expect(page.getByText('Feedback delayed')).toBeVisible();
    }
    await focus.focus();
    const readsBefore = sessionReads;
    const startsBefore = starts;
    const writesBefore = mutations.filter((path) => !path.endsWith('/draft'));
    ready = true;
    release();
    await expect(page.locator('html')).toHaveAttribute('data-grade-ready', 'recovery-ready');
    await expect(focus).toBeFocused();
    await expect(page.getByText(`Step ${step === 'dictation' ? 2 : 3} of 5`)).toBeVisible();
    if (step === 'dictation') {
      await expect(focus).toHaveValue('My active draft must survive late feedback');
    } else {
      await expect(page.getByText('You caught the main idea. Read the detail.')).toBeVisible();
      await expect(focus).toHaveAccessibleDescription('Marked');
      await expect(page.getByText(mark.note, { exact: true })).toBeVisible();
      await expect(
        page.getByRole('list', { name: 'Your marks' }).getByRole('listitem'),
      ).toHaveCount(1);
    }
    expect(sessionReads).toBe(readsBefore);
    expect(starts).toBe(startsBefore);
    expect(mutations.filter((path) => !path.endsWith('/draft'))).toEqual(writesBefore);
    saveDraft();
  });
}
