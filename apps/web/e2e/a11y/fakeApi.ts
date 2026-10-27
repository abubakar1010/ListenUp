import type { Page, Route } from '@playwright/test';

import type { components } from '../../src/api/schema';

type Schema = components['schemas'];

/*
 * One fake API for the accessibility scan (#98). Each state lists only the answers
 * it needs; everything a signed-in page asks for anyway is answered here. The shapes
 * follow the generated schema and the per-feature Playwright specs.
 */

export interface Answer {
  status?: number;
  json?: unknown;
  /** Hold the answer forever, to scan a page while it waits. */
  hang?: boolean;
}

/** Answers keyed by `path` or `METHOD path` (path without `/api/v1`). */
export type Answers = Record<string, Answer | ((url: URL) => Answer)>;

export const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: true,
  deletion_grace_days: 7,
  consents_required: [],
} satisfies Schema['Me'];

/** The labels of the texts in `src/features/legal/texts.ts`, so the legal pages render. */
const VERSIONS = {
  terms: 'terms-2026-1',
  privacy: 'privacy-2026-1',
  voice_recording: 'voice-2026-1',
} satisfies Schema['ConsentVersions'];
const MB = 2 ** 20;

export function problem(status: number, code: string, detail: string, extra = {}): Answer {
  return { status, json: { type: `/problems/${code}`, title: '', status, detail, code, ...extra } };
}

/** Near-silence as an 8 kHz, 8-bit mono WAV, so media elements really load. */
function wav(seconds: number): Buffer {
  const samples = 8000 * seconds;
  const data = Buffer.alloc(44 + samples, 128);
  data.write('RIFF', 0);
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
const AUDIO = wav(35);

function media(route: Route) {
  const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()['range'] ?? '');
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

/** What every signed-in page reads; a state's own answers take precedence. */
const SIGNED_IN: Answers = {
  '/me': { json: LEARNER },
  '/me/consents': {
    json: {
      consents: (['terms', 'privacy'] as const).map((kind) => ({
        kind,
        version: VERSIONS[kind],
        current: true,
        granted_at: '2026-10-01T09:00:00Z',
        withdrawn_at: null,
      })),
      current: VERSIONS,
    } satisfies Schema['Consents'],
  },
  '/me/exports/latest': { json: { export: null } },
  '/library/contents': { json: { items: [], next_cursor: null } },
  '/sessions': { json: { items: [], next_cursor: null } },
  '/uploads/usage': {
    json: {
      used_bytes: 300 * MB,
      quota_bytes: 2048 * MB,
      max_file_bytes: 500 * MB,
      daily_audio: {
        used_seconds: 600,
        limit_seconds: 7200,
        clips_in_progress: 0,
        reserved_seconds: 0,
        can_add: true,
        resets_at: '2030-01-01T00:00:00Z',
      },
    } satisfies Schema['StorageUse'],
  },
};

/**
 * Answers the API for one page. Returns the requests a signed-in page made that no
 * answer covers, so a scan can fail instead of scanning a "not found" screen.
 */
export async function fakeApi(page: Page, answers: Answers, signedIn: boolean) {
  const table: Answers = {
    '/auth/consent-versions': { json: VERSIONS },
    ...(signedIn ? SIGNED_IN : {}),
    ...answers,
  };
  const unanswered: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/events') return route.abort();
    if (path.startsWith('/media/') && !path.endsWith('/peaks')) return media(route);
    const found = table[`${request.method()} ${path}`] ?? table[path];
    if (!found) {
      if (signedIn) unanswered.push(`${request.method()} ${path}`);
      const refusal = signedIn
        ? problem(404, 'not_found', path)
        : problem(401, 'not_signed_in', 'Sign in to continue.');
      return route.fulfill({ status: refusal.status, json: refusal.json });
    }
    const answer = typeof found === 'function' ? found(url) : found;
    if (answer.hang) return new Promise<void>(() => undefined);
    const status = answer.status ?? 200;
    if (status === 204) return route.fulfill({ status });
    return route.fulfill({
      status,
      contentType: status >= 400 ? 'application/problem+json' : 'application/json',
      body: JSON.stringify(answer.json ?? null),
    });
  });
  return unanswered;
}
