import { type Page, type Route } from '@playwright/test';

// The plan API as a fake, shared by the plan specs (#99).
export const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: false,
  deletion_grace_days: 7,
  consents_required: [],
};

export const CLIP = {
  id: 'clip-1',
  title: 'Why cities plant street trees',
  source: 'upload',
  status: 'playable',
  duration_ms: 760_000,
  created_at: '2026-10-03T09:00:00Z',
  last_session_status: null,
};

export type Entry = 'blind' | 'dictation' | 'both';
export type StepName = 'blind' | 'dictation' | 'transcript' | 'card' | 'shadow';

export function pathFor(entry: Entry): StepName[] {
  const first: StepName[] = entry === 'both' ? ['blind', 'dictation'] : [entry];
  return [...first, 'transcript', 'card', 'shadow'];
}

export interface FakeSession {
  id: string;
  entry: Entry;
  passage: { start_ms: number; end_ms: number };
  version: number;
  statuses: Record<string, 'locked' | 'open' | 'done' | 'skipped'>;
}

/** The session as the API shows it, from the fake's state. */
export function view(s: FakeSession) {
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

/** `GET /contents/{id}` for the clip; without peaks the picker draws a bare track. */
export function contentDetail(clip: typeof CLIP) {
  const { id, title, source, status, duration_ms, created_at } = clip;
  return {
    id,
    title,
    source,
    status,
    duration_ms,
    created_at,
    error_code: null,
    error_detail: null,
    has_video: false,
    keep_video: false,
    media_object_id: 'm-1',
    media_url: '/api/v1/media/m-1',
    peaks_url: '/api/v1/media/m-1/peaks',
  };
}

export function problem(route: Route, status: number, code: string, detail: string) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code },
  });
}

/** A signed-in learner with one clip; sessions live in `sessions`. */
export async function fakeApi(page: Page, sessions: FakeSession[] = []) {
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
    if (path === `/contents/${CLIP.id}`) return route.fulfill({ json: contentDetail(CLIP) });
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
    if (session && match![2] === '/blind' && method === 'GET') {
      return route.fulfill({
        json: {
          session_id: session.id,
          passage_start_ms: session.passage.start_ms,
          passage_end_ms: session.passage.end_ms,
          step_status: session.statuses.blind ?? 'locked',
          attempt: null,
        },
      });
    }
    // Only the plan's own writes: a step page's requests fall through to the 404.
    if (session && method !== 'GET' && /^\/(entry|steps\/)/.test(match![2] ?? '')) {
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
