import { expect, test, type Page, type Route } from '@playwright/test';

const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
};

const CLIP = {
  id: 'clip-1',
  title: 'Why cities plant street trees',
  source: 'upload',
  status: 'playable',
  duration_ms: 760_000,
  created_at: '2026-10-03T09:00:00Z',
  last_session_status: null,
};

type Entry = 'blind' | 'dictation' | 'both';
type StepName = 'blind' | 'dictation' | 'transcript' | 'card' | 'shadow';

function pathFor(entry: Entry): StepName[] {
  const first: StepName[] = entry === 'both' ? ['blind', 'dictation'] : [entry];
  return [...first, 'transcript', 'card', 'shadow'];
}

interface FakeSession {
  id: string;
  entry: Entry;
  passage: { start_ms: number; end_ms: number };
  version: number;
  statuses: Record<string, 'locked' | 'open' | 'done' | 'skipped'>;
}

/** The session as the API shows it, from the fake's state. */
function view(s: FakeSession) {
  const path = pathFor(s.entry);
  const steps = path.map((step, index) => ({
    step,
    position: index + 1,
    status: s.statuses[step] ?? 'locked',
  }));
  const open = steps.find((step) => step.status === 'open') ?? null;
  const complete = ['done', 'skipped'].includes(s.statuses.shadow);
  return {
    id: s.id,
    content_id: CLIP.id,
    content_title: CLIP.title,
    passage: s.passage,
    entry: s.entry,
    status: complete ? 'completed' : 'active',
    version: s.version,
    steps,
    step_count: path.length,
    open_step: open?.step ?? null,
    open_position: open?.position ?? null,
    entry_locked: (s.statuses.transcript ?? 'locked') !== 'locked',
    entry_locked_at: null,
    completed_at: complete ? '2026-10-03T10:00:00Z' : null,
    created_at: '2026-10-03T09:00:00Z',
    updated_at: '2026-10-03T09:00:00Z',
  };
}

function problem(route: Route, status: number, code: string, detail: string) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code },
  });
}

/** A signed-in learner with one clip; sessions live in `sessions`. */
async function fakeApi(page: Page, sessions: FakeSession[] = []) {
  const posts: { body: unknown; key: string | undefined }[] = [];
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
    if (path === '/library/contents') {
      return route.fulfill({ json: { items: [CLIP], next_cursor: null } });
    }
    if (path === '/sessions' && method === 'GET') {
      return route.fulfill({ json: { items: sessions.map(view), next_cursor: null } });
    }
    if (path === '/sessions' && method === 'POST') {
      const body = request.postDataJSON() as { entry: Entry; passage: FakeSession['passage'] };
      posts.push({ body, key: request.headers()['idempotency-key'] });
      const created: FakeSession = {
        id: `s-${sessions.length + 1}`,
        entry: body.entry,
        passage: body.passage,
        version: 0,
        statuses: { [pathFor(body.entry)[0]]: 'open' },
      };
      sessions.unshift(created);
      return route.fulfill({ status: 201, json: view(created) });
    }
    const match = path.match(/^\/sessions\/([^/]+)(\/.*)?$/);
    const session = match && sessions.find((s) => s.id === match[1]);
    if (match && !session) return problem(route, 404, 'session_not_found', 'No such session.');
    if (session && !match![2] && method === 'GET') return route.fulfill({ json: view(session) });
    if (session && method !== 'GET') {
      const body = request.postDataJSON() as { version: number; entry?: Entry };
      if (body.version !== session.version) {
        return problem(route, 409, 'session_changed', 'The session changed. Reload and try again.');
      }
      if (match![2] === '/entry') {
        if (view(session).entry_locked) {
          return problem(route, 409, 'entry_locked', 'The entry choice cannot change now.');
        }
        session.entry = body.entry!;
        const next = pathFor(session.entry).find((step) => session.statuses[step] !== 'done');
        session.statuses = Object.fromEntries(
          Object.entries(session.statuses).filter(([, status]) => status === 'done'),
        );
        session.statuses[next!] = 'open';
      } else {
        const step = match![2]!.split('/')[2] as StepName;
        if (!['card', 'shadow'].includes(step)) {
          return problem(route, 409, 'step_not_skippable', 'Only Card and Shadow can be skipped.');
        }
        session.statuses[step] = 'skipped';
        if (step === 'card') session.statuses.shadow = 'open';
      }
      session.version += 1;
      return route.fulfill({ json: view(session) });
    }
    return problem(route, 404, 'not_found', path);
  });
  return { posts };
}

test('a learner starts a plan from the library and sees step 1 of 5', async ({ page }) => {
  const { posts } = await fakeApi(page);
  await page.goto('/library');

  await page.getByRole('link', { name: 'Start a plan on Why cities plant street trees' }).click();
  await expect(page).toHaveURL('/contents/clip-1/plan');
  await expect(page.getByRole('heading', { name: 'Start a plan', level: 1 })).toBeVisible();

  // 12:40 is under 15 minutes, so the whole clip is chosen; Blind is ticked.
  await expect(page.getByRole('radio', { name: /Whole clip/ })).toBeChecked();
  await expect(page.getByText('Your plan: 4 steps')).toBeVisible();
  await page.getByRole('checkbox', { name: /Dictation/ }).check();
  await expect(page.getByText('Your plan: 5 steps')).toBeVisible();

  await page.getByRole('button', { name: 'Start plan' }).click();

  await expect(page).toHaveURL('/sessions/s-1');
  await expect(page.getByText('Step 1 of 5')).toBeVisible();
  const steps = page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem');
  await expect(steps).toHaveCount(5);
  await expect(steps.first()).toHaveAttribute('aria-current', 'step');
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toEqual({
    content_id: 'clip-1',
    passage: { start_ms: 0, end_ms: 760_000 },
    entry: 'both',
  });
  expect(posts[0].key).toBeTruthy();

  // Back in the library, the plan is listed with where it stands.
  await page.goto('/library');
  const plans = page.getByRole('region', { name: 'Your plans' });
  await expect(plans).toContainText('Step 1 of 5 · Blind');
  await plans.getByRole('link', { name: /Resume/ }).click();
  await expect(page).toHaveURL('/sessions/s-1');
});

test('a part of the clip is chosen with the keyboard at 360 px', async ({ page }) => {
  const { posts } = await fakeApi(page);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/contents/clip-1/plan');

  await page.getByRole('radio', { name: /A part of it/ }).check();
  await page.getByRole('textbox', { name: 'Start' }).fill('02:10');
  await page.getByRole('textbox', { name: 'End' }).fill('02:20');
  await page.getByRole('textbox', { name: 'End' }).press('Enter');
  await expect(page.getByRole('textbox', { name: 'End' })).toHaveAttribute('aria-invalid', 'true');
  expect(posts).toHaveLength(0);

  await page.getByRole('textbox', { name: 'End' }).fill('04:40');
  await page.getByRole('button', { name: 'Start plan' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL('/sessions/s-1');
  await expect(page.getByText('Step 1 of 4')).toBeVisible();
  expect(posts[0].body).toMatchObject({ passage: { start_ms: 130_000, end_ms: 280_000 } });

  for (const path of ['/contents/clip-1/plan', '/sessions/s-1', '/library']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
});

test('before Transcript, adding Dictation makes the plan 5 steps', async ({ page }) => {
  await fakeApi(page, [
    {
      id: 's-1',
      entry: 'blind',
      passage: { start_ms: 0, end_ms: 150_000 },
      version: 0,
      statuses: { blind: 'open' },
    },
  ]);
  await page.goto('/sessions/s-1');

  await expect(page.getByText('Step 1 of 4')).toBeVisible();
  await page.getByRole('button', { name: 'Change entry' }).click();
  const panel = page.getByRole('region', { name: 'Change how you start' });
  await panel.getByRole('checkbox', { name: /Dictation/ }).check();
  await expect(panel.getByText('Your plan becomes: 5 steps')).toBeVisible();
  await panel.getByRole('button', { name: 'Save change' }).click();

  await expect(page.getByText('Step 1 of 5')).toBeVisible();
  await expect(page.getByRole('list', { name: 'Plan steps' }).getByRole('listitem')).toHaveCount(5);
  await expect(page.getByRole('button', { name: 'Change entry' })).toBeFocused();
});

test('Card and Shadow are skipped only after confirming, which completes the plan', async ({
  page,
}) => {
  await fakeApi(page, [
    {
      id: 's-1',
      entry: 'dictation',
      passage: { start_ms: 0, end_ms: 150_000 },
      version: 2,
      statuses: { dictation: 'done', transcript: 'done', card: 'open' },
    },
  ]);
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/sessions/s-1');

  await expect(page.getByText('Step 3 of 4')).toBeVisible();
  await expect(page.getByText('Entry locked')).toBeVisible();
  const skipCard = page.getByRole('button', { name: 'Skip Card' });
  await skipCard.focus();
  await page.keyboard.press('Enter');

  const dialog = page.getByRole('dialog', { name: 'Skip Card?' });
  await expect(dialog.getByRole('button', { name: 'Make a card' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Skip Card' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Make a card' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(skipCard).toBeFocused();
  await expect(page.getByText('Step 3 of 4')).toBeVisible();

  await skipCard.click();
  await dialog.getByRole('button', { name: 'Skip Card' }).click();
  await expect(page.getByText('Step 4 of 4')).toBeVisible();

  await page.getByRole('button', { name: 'Skip Shadow' }).click();
  await page.getByRole('button', { name: 'Skip Shadow and finish' }).click();
  await expect(page.getByText('All 4 steps finished')).toBeVisible();
  await expect(page.getByText('Skipped: Card and Shadow.')).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
