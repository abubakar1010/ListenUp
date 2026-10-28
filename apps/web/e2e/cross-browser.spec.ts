import { expect, test } from './test';
import { fakeApi, pathFor, type Entry, type FakeSession, type StepName } from './plan-api';

// Cross-browser plan paths (#99, NFR-COM-1). The API is a fake, so this proves what
// each browser does with the responses, not the server: the server's step gate is
// proved by the API integration tests, the Blind rules (AT-2) by blind.spec.ts and the
// Blind API tests. The whole suite runs on the browser matrix; these tests add the
// plan paths themselves.

const NAMES: Record<StepName, string> = {
  blind: 'Blind',
  dictation: 'Dictation',
  transcript: 'Transcript',
  card: 'Card',
  shadow: 'Shadow',
};

/** What the server does when a step is completed: it is done and the next one opens. */
function complete(session: FakeSession) {
  const path = pathFor(session.entry);
  const open = path.find((step) => session.statuses[step] === 'open')!;
  session.statuses[open] = 'done';
  const next = path[path.indexOf(open) + 1];
  if (next) session.statuses[next] = 'open';
  session.version += 1;
}

const PATHS: { entry: Entry; ticks: { blind: boolean; dictation: boolean }; steps: number }[] = [
  { entry: 'blind', ticks: { blind: true, dictation: false }, steps: 4 },
  { entry: 'dictation', ticks: { blind: false, dictation: true }, steps: 4 },
  { entry: 'both', ticks: { blind: true, dictation: true }, steps: 5 },
];

for (const { entry, ticks, steps } of PATHS) {
  test(`AT-7: the ${entry} path is ${steps} steps that unlock in order`, async ({ page }) => {
    const sessions: FakeSession[] = [];
    const { posts } = await fakeApi(page, sessions);
    await page.goto('/contents/clip-1/plan');

    const blind = page.getByRole('checkbox', { name: /Blind/ });
    const dictation = page.getByRole('checkbox', { name: /Dictation/ });
    // Blind starts ticked; set each box to what this path needs, ticking before unticking
    // so the form never has neither.
    if (ticks.dictation) await dictation.check();
    if (!ticks.blind) await blind.uncheck();
    await expect(page.getByText(`Your plan: ${steps} steps`)).toBeVisible();
    await page.getByRole('button', { name: 'Start plan' }).click();

    await expect(page).toHaveURL('/sessions/s-1');
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toMatchObject({ entry });
    const names = pathFor(entry).map((step) => NAMES[step]);
    const list = page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem');

    // Walk the plan: at every position the open step is current and the rest are
    // locked, or done behind it.
    const path = pathFor(entry);
    for (const [index, step] of path.entries()) {
      await page.goto('/sessions/s-1');
      await expect(page.getByText(`Step ${index + 1} of ${steps}`)).toBeVisible();
      await expect(list).toHaveCount(steps);
      for (const [position, name] of names.entries()) {
        const item = list.nth(position);
        await expect(item).toContainText(name);
        if (position === index) await expect(item).toHaveAttribute('aria-current', 'step');
        else await expect(item).not.toHaveAttribute('aria-current', 'step');
        if (position > index) await expect(item).toContainText(/locked/i);
      }
      // The entry can change until Transcript opens, and not after (FR-PL-6).
      const entryLocked = step === 'transcript' || index > path.indexOf('transcript');
      if (entryLocked) {
        await expect(page.getByText('Entry locked')).toBeVisible();
        await expect(page.getByRole('button', { name: 'Change entry' })).toHaveCount(0);
      } else {
        await expect(page.getByRole('button', { name: 'Change entry' })).toBeVisible();
      }
      if (step === 'shadow') break;
      complete(sessions[0]);
    }
  });
}

test('AT-7: adding Dictation before Transcript makes Blind a 5-step plan', async ({ page }) => {
  const sessions: FakeSession[] = [];
  await fakeApi(page, sessions);
  await page.goto('/contents/clip-1/plan');
  await page.getByRole('button', { name: 'Start plan' }).click();
  await expect(page.getByText('Step 1 of 4')).toBeVisible();

  await page.getByRole('button', { name: 'Change entry' }).click();
  const panel = page.getByRole('region', { name: 'Change how you start' });
  await panel.getByRole('checkbox', { name: /Dictation/ }).check();
  await panel.getByRole('button', { name: 'Save change' }).click();
  await expect(page.getByText('Step 1 of 5')).toBeVisible();

  // Once Transcript is open the choice is gone, also after a reload.
  complete(sessions[0]);
  complete(sessions[0]);
  await page.reload();
  await expect(page.getByText('Step 3 of 5')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Change entry' })).toHaveCount(0);
});

test('AT-8: a second browser signs in and finds the library, plan, marks and cards', async ({
  browser,
}) => {
  const learner = {
    id: 'learner-99',
    email: 'second@example.com',
    display_name: null,
    email_verified: false,
    deletion_grace_days: 7,
    consents_required: [],
  };
  const clip = {
    id: 'clip-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: 150_000,
    created_at: '2026-10-03T09:00:00Z',
    last_session_status: 'active',
  };
  const session = {
    id: 's-1',
    content_id: clip.id,
    content_title: clip.title,
    passage: { start_ms: 0, end_ms: 150_000 },
    entry: 'blind',
    status: 'active',
    version: 1,
    steps: [
      { step: 'blind', position: 1, status: 'done' },
      { step: 'transcript', position: 2, status: 'open' },
      { step: 'card', position: 3, status: 'locked' },
      { step: 'shadow', position: 4, status: 'locked' },
    ],
    step_count: 4,
    open_step: 'transcript',
    open_position: 2,
    entry_locked: true,
    entry_locked_at: '2026-10-03T09:30:00Z',
    completed_at: null,
    created_at: '2026-10-03T09:00:00Z',
    updated_at: '2026-10-03T09:30:00Z',
  };
  const mark = {
    id: 'm1',
    session_id: 's-1',
    source: 'manual',
    status: 'confirmed',
    at_ms: 11_000,
    source_url: '/contents/clip-1?at_ms=11000',
    created_at: '2026-10-03T09:20:00Z',
    note: 'linking sound',
  };
  const card = {
    id: 'card-1',
    written_form: 'could have',
    heard_form: 'could of',
    audio_status: 'ready',
    source_url: '/contents/clip-1?at_ms=11000',
    at_ms: 11_000,
  };

  // A browser that has never seen this learner: its own empty storage, shared server.
  const context = await browser.newContext();
  try {
    expect(await context.storageState()).toEqual({ cookies: [], origins: [] });
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
        signedIn = true;
        return route.fulfill({ json: learner });
      }
      if (!signedIn) return route.fulfill({ status: 401, json: { code: 'not_signed_in' } });
      if (path === '/me') return route.fulfill({ json: learner });
      if (path === '/library/contents')
        return route.fulfill({ json: { items: [clip], next_cursor: null } });
      if (path === '/sessions')
        return route.fulfill({ json: { items: [session], next_cursor: null } });
      if (path === '/marks') return route.fulfill({ json: { marks: [mark], next_cursor: null } });
      if (path === '/cards')
        return route.fulfill({ json: { cards: [card], remaining: 1, next_cursor: null } });
      if (path === '/events')
        return route.fulfill({ contentType: 'text/event-stream', body: ': connected\n\n' });
      if (path === `/cards/${card.id}/reviews`)
        return route.fulfill({ json: { reviews: [], next_cursor: null } });
      return route.fulfill({ status: 404, json: { code: 'not_found', detail: path } });
    });
    const page = await context.newPage();
    await page.goto('/library');
    await page.getByLabel('Email', { exact: true }).fill(learner.email);
    await page.getByLabel('Password', { exact: true }).fill('correct horse battery');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();

    await expect(page.getByText(clip.title).first()).toBeVisible();
    await expect(page.getByRole('region', { name: 'Your plans' })).toContainText(
      'Step 2 of 4 · Transcript',
    );
    await page.goto('/marks');
    await expect(page.getByRole('heading', { name: 'Saved marks' })).toBeVisible();
    await expect(page.getByText('linking sound')).toBeVisible();
    await page.goto('/cards');
    await expect(page.getByRole('heading', { name: 'Review cards' })).toBeVisible();
    await expect(page.getByText('Card 1 of 1')).toBeVisible();
  } finally {
    await context.close();
  }
});
