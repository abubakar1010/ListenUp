import type { Page, Route } from '@playwright/test';

import type { components } from '../../src/api/schema';

type Schema = components['schemas'];

/*
 * A stateful fake of the API for one plan from start to finish (#98, AT-7): the
 * keyboard-path specs drive every step against it, so each write changes what the
 * next read returns, as the real API would. Shapes follow the generated schema.
 * Like the other Playwright specs, it proves browser behavior against these answers,
 * not the server; the API's own rules are proved by its integration tests.
 */

export type Entry = Schema['Entry'];
type Step = Schema['Step'];
type Status = 'locked' | 'open' | 'done' | 'skipped';
type Passage = Schema['Session']['passage'];

const SESSION_ID = 's-1';
const NOW = '2026-10-31T09:00:00Z';
/** 45 s: under 60 s, so Shadow uses the whole passage and needs no segment choice. */
const DURATION_MS = 45_000;

export const LEARNER = {
  id: '1',
  email: 'learner@example.com',
  display_name: null,
  email_verified: true,
  deletion_grace_days: 7,
  consents_required: [],
} satisfies Schema['Me'];

export const CLIP = {
  id: 'clip-1',
  title: 'Why cities plant street trees',
  source: 'upload',
  status: 'playable',
  duration_ms: DURATION_MS,
  created_at: '2026-10-03T09:00:00Z',
  stage: null,
  queue_position: null,
  last_session_status: null,
} satisfies Schema['LibraryItem'];

const DETAIL = {
  id: CLIP.id,
  title: CLIP.title,
  source: CLIP.source,
  status: CLIP.status,
  duration_ms: CLIP.duration_ms,
  created_at: CLIP.created_at,
  stage: null,
  queue_position: null,
  error_code: null,
  error_detail: null,
  has_video: false,
  keep_video: false,
  media_object_id: 'm-1',
  media_url: '/api/v1/media/m-1',
  peaks_url: null,
} satisfies Schema['ContentDetail'];

const VERSIONS = {
  terms: 'terms-2026-1',
  privacy: 'privacy-2026-1',
  voice_recording: 'voice-2026-1',
} satisfies Schema['ConsentVersions'];

/** The passage's words, as Transcript shows them. */
export const WORDS = ['Cities', 'plant', 'trees.', 'Shade', 'cools', 'streets.'];
/** What the learner types in Dictation: "plant" comes out as "plan". */
export const TYPED = 'Cities plan trees. Shade cools streets.';

function transcript(passage: Passage): Schema['TranscriptReview'] {
  const word = (index: number, start: number) => ({
    index,
    text: WORDS[index]!,
    start_ms: start,
    end_ms: start + 1500,
    edited: false,
  });
  return {
    session_id: SESSION_ID,
    passage,
    media_url: '/api/v1/media/m-1',
    lines: [
      { index: 0, start_ms: 0, end_ms: 4500, words: [0, 1, 2].map((i) => word(i, i * 1500)) },
      {
        index: 1,
        start_ms: 20_000,
        end_ms: 24_500,
        words: [3, 4, 5].map((i) => word(i, 20_000 + (i - 3) * 1500)),
      },
    ],
  };
}

const SCORED: Schema['DictationResult'] = {
  accuracy: 83,
  counts: { correct: 5, spelling_slip: 0, wrong: 1, missing: 0, extra: 0 },
  items: WORDS.map((word, index) =>
    index === 1
      ? { index, status: 'wrong', word, typed: 'plan' }
      : { index, status: 'correct', word, typed: word },
  ),
};

/** Near-silence as an 8 kHz, 8-bit mono WAV, so media elements really load and play. */
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
const AUDIO = wav(DURATION_MS / 1000 + 1);

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

function problem(route: Route, status: number, code: string, detail: string) {
  return route.fulfill({
    status,
    contentType: 'application/problem+json',
    json: { type: `/problems/${code}`, title: '', status, detail, code },
  });
}

export function pathFor(entry: Entry): Step[] {
  const first: Step[] = entry === 'both' ? ['blind', 'dictation'] : [entry];
  return [...first, 'transcript', 'card', 'shadow'];
}

/** What the plan server holds; the spec reads it to check what was saved. */
export interface PlanState {
  entry: Entry | null;
  passage: Passage;
  version: number;
  statuses: Partial<Record<Step, Status>>;
  blind: Schema['BlindAttempt'] | null;
  voids: string[];
  draft: { text: string; version: number };
  dictation: 'none' | 'active' | 'scored';
  marks: Schema['Mark'][];
  cards: Schema['Card'][];
  voiceConsent: boolean;
  rounds: Schema['Round'][];
  uploads: number[];
  /** Requests the fake has no answer for: a path the spec must cover, so it fails. */
  unanswered: string[];
}

function sessionView(state: PlanState): Schema['Session'] {
  const path = pathFor(state.entry!);
  const steps = path.map((step, index) => ({
    step,
    position: index + 1,
    status: state.statuses[step] ?? 'locked',
  }));
  const open = steps.find((step) => step.status === 'open') ?? null;
  const complete = ['done', 'skipped'].includes(state.statuses.shadow ?? '');
  return {
    id: SESSION_ID,
    content_id: CLIP.id,
    content_title: CLIP.title,
    passage: state.passage,
    entry: state.entry!,
    status: complete ? 'completed' : 'active',
    version: state.version,
    steps,
    step_count: path.length,
    open_step: open?.step ?? null,
    open_position: open?.position ?? null,
    entry_locked: (state.statuses.transcript ?? 'locked') !== 'locked',
    entry_locked_at: null,
    completed_at: complete ? NOW : null,
    created_at: NOW,
    updated_at: NOW,
  };
}

/** Finish `step` and open the next one on the path, as `complete_step` does. */
function complete(state: PlanState, step: Step) {
  const path = pathFor(state.entry!);
  state.statuses[step] = 'done';
  const next = path[path.indexOf(step) + 1];
  if (next) state.statuses[next] = 'open';
  state.version += 1;
}

function blindAttempt(state: PlanState, overrides: Partial<Schema['BlindAttempt']> = {}) {
  return {
    id: 'a-1',
    session_id: SESSION_ID,
    status: 'active',
    void_reason: null,
    started_at: NOW,
    finished_at: null,
    passage_start_ms: state.passage.start_ms,
    passage_end_ms: state.passage.end_ms,
    position_ms: 0,
    resume_count: 0,
    resume_stop_ms: null,
    listen_complete: false,
    gist_text: null,
    ...overrides,
  } satisfies Schema['BlindAttempt'];
}

function round(number: number): Schema['Round'] {
  return {
    id: `round-${number}`,
    round: number,
    transcript_shown: number === 1,
    playback_status: 'ready',
    recorded_at: null,
    recording_available: false,
    feedback: null,
  };
}

function markFor(state: PlanState, range: { id?: string; word_from: number; word_to: number }) {
  const lines = transcript(state.passage).lines.flatMap((line) => line.words);
  return {
    id: range.id ?? `mark-${state.marks.length + 1}`,
    session_id: SESSION_ID,
    word_from: range.word_from,
    word_to: range.word_to,
    at_ms: lines[range.word_from]!.start_ms,
    note: null,
    source: 'manual',
    status: 'confirmed',
    tag: null,
    created_at: NOW,
  } satisfies Schema['Mark'];
}

function phraseOf(state: PlanState, markId: string | null) {
  const mark = state.marks.find((m) => m.id === markId);
  return mark ? WORDS.slice(mark.word_from, mark.word_to + 1).join(' ') : '';
}

type Handler = (args: {
  route: Route;
  state: PlanState;
  method: string;
  path: string;
  url: URL;
  body: () => Record<string, unknown>;
}) => Promise<void> | void | false;

/** One route per entry: `METHOD /path` with `:id` for a path segment. */
const ROUTES: [string, Handler][] = [
  ['GET /me', ({ route }) => route.fulfill({ json: LEARNER })],
  ['GET /auth/consent-versions', ({ route }) => route.fulfill({ json: VERSIONS })],
  ['GET /me/consents', ({ route, state }) => route.fulfill({ json: consents(state) })],
  [
    'POST /me/consents',
    ({ route, state, body }) => {
      if (body()['kind'] !== 'voice_recording') return false;
      state.voiceConsent = true;
      return route.fulfill({ status: 201, json: consents(state) });
    },
  ],
  [
    'GET /library/contents',
    ({ route }) => route.fulfill({ json: { items: [CLIP], next_cursor: null } }),
  ],
  [
    'GET /uploads/usage',
    ({ route }) =>
      route.fulfill({
        json: {
          used_bytes: 0,
          quota_bytes: 2 ** 31,
          max_file_bytes: 500 * 2 ** 20,
          daily_audio: {
            used_seconds: 0,
            limit_seconds: 7200,
            clips_in_progress: 0,
            reserved_seconds: 0,
            can_add: true,
            resets_at: '2030-01-01T00:00:00Z',
          },
        } satisfies Schema['StorageUse'],
      }),
  ],
  [`GET /contents/${CLIP.id}`, ({ route }) => route.fulfill({ json: DETAIL })],
  [
    'GET /sessions',
    ({ route, state }) =>
      route.fulfill({
        json: { items: state.entry ? [sessionView(state)] : [], next_cursor: null },
      }),
  ],
  [
    'POST /sessions',
    ({ route, state, body }) => {
      const { entry, passage } = body() as { entry: Entry; passage: Passage };
      state.entry = entry;
      state.passage = passage;
      state.statuses = { [pathFor(entry)[0]!]: 'open' };
      return route.fulfill({ status: 201, json: sessionView(state) });
    },
  ],
  ['GET /sessions/:id', ({ route, state }) => route.fulfill({ json: sessionView(state) })],

  // Blind (#64 to #69): one attempt, which the spec plays to the end.
  [
    'GET /sessions/:id/blind',
    ({ route, state }) =>
      route.fulfill({
        json: {
          session_id: SESSION_ID,
          passage_start_ms: state.passage.start_ms,
          passage_end_ms: state.passage.end_ms,
          step_status: state.statuses.blind ?? 'locked',
          attempt: state.blind,
        } satisfies Schema['BlindStep'],
      }),
  ],
  [
    'POST /sessions/:id/blind/attempts',
    ({ route, state }) => {
      state.blind = blindAttempt(state);
      return route.fulfill({
        status: 201,
        json: {
          attempt: state.blind,
          media_url: '/api/v1/blind/attempts/a-1/media/token',
          heartbeat_interval_ms: 5_000,
          resume_delay_ms: 3_000,
        } satisfies Schema['StartedAttempt'],
      });
    },
  ],
  ['GET /blind/attempts/a-1/media/token', ({ route }) => media(route)],
  [
    'POST /blind/attempts/a-1/heartbeat',
    ({ route, state, body }) => {
      const beat = body() as { position_ms: number; state: string };
      if (beat.state === 'ended')
        state.blind = blindAttempt(state, { position_ms: beat.position_ms, listen_complete: true });
      return route.fulfill({
        json: {
          action: 'continue',
          attempt: state.blind!,
          resume_from_ms: null,
          resume_delay_ms: 3_000,
        } satisfies Schema['HeartbeatOut'],
      });
    },
  ],
  [
    'POST /blind/attempts/a-1/void',
    ({ route, state, body }) => {
      const reason = String(body()['reason']);
      state.voids.push(reason);
      state.blind = blindAttempt(state, { status: 'voided', void_reason: reason as never });
      return route.fulfill({ json: state.blind });
    },
  ],
  [
    'POST /blind/attempts/a-1/gist',
    ({ route, state, body }) => {
      state.blind = blindAttempt(state, {
        status: 'submitted',
        gist_text: String(body()['text']),
        listen_complete: true,
        position_ms: state.passage.end_ms,
      });
      complete(state, 'blind');
      return route.fulfill({
        status: 201,
        json: {
          attempt: state.blind,
          open_step: sessionView(state).open_step,
          session_version: state.version,
        } satisfies Schema['GistSubmitted'],
      });
    },
  ],
  [
    // Grading is not ready within the session: the plan continues without it.
    'GET /gists/a-1/grade',
    ({ route, state }) =>
      route.fulfill({
        json: {
          status: 'pending',
          wait_ms: 60_000,
          gist: state.blind?.gist_text ?? null,
        } satisfies Partial<Schema['GistFeedback']>,
      }),
  ],

  // Dictation (#51 to #56).
  [
    'POST /sessions/:id/dictation/attempts',
    ({ route, state }) => {
      state.dictation = state.dictation === 'none' ? 'active' : state.dictation;
      return route.fulfill({
        json: {
          id: 'att-1',
          session_id: SESSION_ID,
          status: 'active',
          started_at: NOW,
          resumed: state.draft.version > 0,
          draft_text: state.draft.text,
          draft_version: state.draft.version,
          draft_updated_at: NOW,
          passage: state.passage,
          media_url: '/api/v1/media/m-1',
        } satisfies Schema['DictationAttempt'],
      });
    },
  ],
  ['POST /dictation/attempts/att-1/listen', ({ route }) => route.fulfill({ status: 204 })],
  [
    'PUT /dictation/attempts/att-1/draft',
    ({ route, state, body }) => {
      state.draft = { text: String(body()['draft_text']), version: state.draft.version + 1 };
      return route.fulfill({
        json: {
          draft_version: state.draft.version,
          updated_at: NOW,
        } satisfies Schema['SavedDraft'],
      });
    },
  ],
  [
    'POST /dictation/attempts/att-1/submit',
    ({ route, state, body }) => {
      state.draft.text = String(body()['text'] ?? state.draft.text);
      state.dictation = 'scored';
      complete(state, 'dictation');
      return route.fulfill({
        status: 202,
        json: {
          attempt_id: 'att-1',
          status: 'submitted',
          scoring_status: 'scored',
        } satisfies Schema['DictationSubmission'],
      });
    },
  ],
  [
    'GET /sessions/:id/dictation/attempt',
    ({ route, state }) =>
      state.dictation === 'scored'
        ? route.fulfill({
            json: {
              id: 'att-1',
              session_id: SESSION_ID,
              status: 'submitted',
              scoring_status: 'scored',
              result: SCORED,
            } satisfies Schema['DictationAttemptView'],
          })
        : problem(route, 404, 'attempt_not_found', 'No Dictation attempt.'),
  ],
  [
    'GET /dictation/attempts/att-1/marks',
    ({ route, state }) =>
      route.fulfill({ json: { marks: state.marks.filter((m) => m.source === 'dictation') } }),
  ],
  [
    'POST /dictation/attempts/att-1/marks',
    ({ route, state, body }) => {
      const ranges = body()['marks'] as { word_from: number; word_to: number }[];
      const added = ranges.map((range) => {
        const mark: Schema['Mark'] = {
          ...markFor(state, range),
          source: 'dictation',
          status: 'suggested',
        };
        state.marks.push(mark);
        return mark;
      });
      return route.fulfill({ status: 201, json: { marks: added } });
    },
  ],

  // Transcript and marks (#57 to #61).
  [
    'GET /sessions/:id/transcript',
    ({ route, state }) => route.fulfill({ json: transcript(state.passage) }),
  ],
  [
    'GET /sessions/:id/marks',
    ({ route, state }) => route.fulfill({ json: { marks: state.marks } }),
  ],
  [
    'POST /sessions/:id/marks',
    ({ route, state, body }) => {
      const sent = body() as { id: string; word_from: number; word_to: number };
      const existing = state.marks.find((m) => m.id === sent.id);
      if (existing) return route.fulfill({ json: existing });
      const mark = markFor(state, sent);
      state.marks.push(mark);
      return route.fulfill({ status: 201, json: mark });
    },
  ],
  [
    'PUT /sessions/:id/marks/:mark/status',
    ({ route, state, path }) => {
      const mark = state.marks.find((m) => path.includes(`/marks/${m.id}/`));
      if (!mark) return false;
      mark.status = 'confirmed';
      return route.fulfill({ json: mark });
    },
  ],
  [
    'PUT /sessions/:id/marks/:mark/tag',
    ({ route, state, path, body }) => {
      const mark = state.marks.find((m) => path.includes(`/marks/${m.id}/`));
      if (!mark) return false;
      mark.tag = body()['tag'] as Schema['Mark']['tag'];
      return route.fulfill({ json: mark });
    },
  ],
  [
    'PATCH /sessions/:id/marks/:mark',
    ({ route, state, path, body }) => {
      const mark = state.marks.find((m) => path.endsWith(`/marks/${m.id}`));
      if (!mark) return false;
      mark.note = (body()['note'] as string | null) ?? null;
      return route.fulfill({ json: mark });
    },
  ],
  [
    'POST /sessions/:id/transcript/complete',
    ({ route, state }) => {
      complete(state, 'transcript');
      return route.fulfill({ status: 204 });
    },
  ],

  // Card (#72 to #74): at most two per session.
  [
    'GET /cards',
    ({ route, state }) =>
      route.fulfill({
        json: {
          cards: state.cards,
          remaining: 2 - state.cards.length,
          next_cursor: null,
        } satisfies Schema['CardList'],
      }),
  ],
  [
    'GET /sessions/:id/cards/suggestions',
    ({ route, state }) =>
      route.fulfill({
        json: {
          suggestions: state.marks.map((mark) => ({
            mark_id: mark.id,
            phrase: phraseOf(state, mark.id),
            reasons: [],
            suggested: false,
          })),
        } satisfies Schema['CardSuggestions'],
      }),
  ],
  [
    'POST /sessions/:id/cards',
    ({ route, state, body }) => {
      const sent = body() as { mark_id: string | null; written_form: string; heard_form: string };
      const card: Schema['Card'] = {
        id: `card-${state.cards.length + 1}`,
        session_id: SESSION_ID,
        content_id: CLIP.id,
        mark_id: sent.mark_id,
        written_form: sent.written_form,
        heard_form: sent.heard_form,
        slot: state.cards.length + 1,
        at_ms: state.marks.find((m) => m.id === sent.mark_id)?.at_ms ?? 0,
        audio_status: 'ready',
        source_url: `/contents/${CLIP.id}?at_ms=0`,
        created_at: NOW,
      };
      state.cards.push(card);
      return route.fulfill({ status: 201, json: card });
    },
  ],
  ['GET /cards/:card/audio', ({ route }) => media(route)],
  [
    'POST /sessions/:id/cards/complete',
    ({ route, state }) => {
      complete(state, 'card');
      return route.fulfill({ status: 204 });
    },
  ],

  // Shadow (#77 to #81, #87): the whole passage, three recorded rounds.
  [
    'GET /sessions/:id/shadow/segment',
    ({ route, state }) => route.fulfill({ json: segment(state) }),
  ],
  [
    'GET /sessions/:id/shadow/rounds',
    ({ route, state }) =>
      route.fulfill({
        json: {
          segment: segment(state),
          rounds: state.rounds,
          current: state.rounds.at(-1) ?? null,
          ...(state.rounds.at(-1)?.round === 1 && !state.rounds[0]!.recording_available
            ? { text: WORDS.join(' ') }
            : {}),
        } satisfies Schema['Rounds'],
      }),
  ],
  [
    'POST /sessions/:id/shadow/rounds/:n/start',
    ({ route, state, path }) => {
      const number = Number(path.split('/').at(-2));
      if (!state.rounds.some((r) => r.round === number)) state.rounds.push(round(number));
      return route.fulfill({ status: 204 });
    },
  ],
  [
    'POST /sessions/:id/shadow/rounds/:n/playback-ended',
    ({ route, state, path }) => {
      const number = Number(path.split('/').at(-2));
      state.rounds[number - 1]!.playback_status = 'ended';
      return route.fulfill({ status: 204 });
    },
  ],
  [
    'POST /sessions/:id/shadow/rounds/:n/recording',
    ({ route, state, path, body }) => {
      const number = Number(path.split('/').at(-2));
      const mime = String(body()['mime']);
      return route.fulfill({
        json: {
          round_id: state.rounds[number - 1]!.id,
          upload: {
            url: `/storage-e2e/${number}`,
            method: 'PUT',
            headers: { 'Content-Type': mime },
            expires_at: '2030-01-01T00:00:00Z',
          },
        } satisfies Schema['RecordingUpload'],
      });
    },
  ],
  [
    'POST /shadow/rounds/:round/complete',
    ({ route, state, path }) => {
      const recorded = state.rounds.find((r) => path.includes(`/${r.id}/`));
      if (!recorded) return false;
      recorded.recorded_at = NOW;
      recorded.recording_available = true;
      recorded.feedback = 'unavailable';
      // FR-SH-6: three recorded rounds finish Shadow, whatever grading does (#87).
      if (state.rounds.filter((r) => r.recording_available).length === 3) complete(state, 'shadow');
      return route.fulfill({ status: 204 });
    },
  ],
  ['GET /shadow/rounds/:round/recording', ({ route }) => media(route)],
];

function consents(state: PlanState): Schema['Consents'] {
  return {
    consents: [
      ...(['terms', 'privacy'] as const).map((kind) => ({
        kind,
        version: VERSIONS[kind],
        current: true,
        granted_at: NOW,
        withdrawn_at: null,
      })),
      ...(state.voiceConsent
        ? [
            {
              kind: 'voice_recording' as const,
              version: VERSIONS.voice_recording,
              current: true,
              granted_at: NOW,
              withdrawn_at: null,
            },
          ]
        : []),
    ],
    current: VERSIONS,
  };
}

function segment(state: PlanState): Schema['Segment'] {
  return {
    session_id: SESSION_ID,
    start_ms: state.passage.start_ms,
    end_ms: state.passage.end_ms,
    chosen_by: 'system',
    mark_count: state.marks.length,
    locked_at: state.rounds.length > 0 ? NOW : null,
  };
}

function matcher(pattern: string) {
  const [method, path] = pattern.split(' ') as [string, string];
  const regex = new RegExp(`^${path.replace(/:[a-z]+/g, '[^/]+')}$`);
  return (m: string, p: string) => m === method && regex.test(p);
}
const MATCHERS = ROUTES.map(([pattern, handler]) => [matcher(pattern), handler] as const);

/** Answer the API for one plan on `page`; returns the state the spec can inspect. */
export async function planServer(page: Page): Promise<PlanState> {
  const state: PlanState = {
    entry: null,
    passage: { start_ms: 0, end_ms: DURATION_MS },
    version: 0,
    statuses: {},
    blind: null,
    voids: [],
    draft: { text: '', version: 0 },
    dictation: 'none',
    marks: [],
    cards: [],
    voiceConsent: false,
    rounds: [],
    uploads: [],
    unanswered: [],
  };
  await page.route('**/storage-e2e/**', async (route) => {
    state.uploads.push(Number(route.request().url().split('/').at(-1)));
    await route.fulfill({ status: 200 });
  });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const method = request.method();
    if (path === '/health') {
      return route.fulfill({
        json: { status: 'ok' },
        headers: { 'Set-Cookie': 'listenup_csrf=e2e-token; Path=/; SameSite=Lax' },
      });
    }
    if (path === '/events') return route.abort();
    if (path.startsWith('/media/')) return media(route);
    const body = () => (request.postDataJSON() ?? {}) as Record<string, unknown>;
    for (const [matches, handler] of MATCHERS) {
      if (!matches(method, path)) continue;
      const handled = await handler({ route, state, method, path, url, body });
      if (handled !== false) return;
    }
    state.unanswered.push(`${method} ${path}`);
    return problem(route, 404, 'not_found', path);
  });
  return state;
}
