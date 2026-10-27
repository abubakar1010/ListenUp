import type { Locator, Page } from '@playwright/test';

import type { components } from '../../src/api/schema';
import { sessionFixture } from '../../src/features/session/fixtures';
import { ISSUE } from './allowlist';
import { LEARNER, problem, type Answers } from './fakeApi';

type Schema = components['schemas'];

/*
 * Every route and main state the accessibility scan visits (#98). A new screen or
 * state adds an entry here; `owner` marks a screen another open story is changing.
 */

export interface ScanState {
  /** Stable name: the allowlist and the report refer to it. */
  name: string;
  path: string;
  signedIn?: boolean;
  answers?: Answers;
  /** Steps that reach the state after the page loads. */
  act?: (page: Page) => Promise<void>;
  /** Visible once the state is on screen; the scan waits for it. */
  ready: (page: Page) => Locator;
  /** Only at this width class; the 360 px plan sheet has no desktop counterpart. */
  only?: 'narrow';
  /** The open story that owns this screen; its violations are tracked there, not fixed here. */
  owner?: string;
  /** The state is an error or warning, so an alert is expected on screen. */
  alert?: true;
}

const heading = (name: string | RegExp) => (page: Page) =>
  page.getByRole('heading', { level: 1, name });

const ITEM = {
  id: 'clip-1',
  title: 'Why cities plant street trees',
  source: 'upload',
  status: 'playable',
  duration_ms: 760_000,
  created_at: '2026-10-03T09:00:00Z',
  stage: null,
  queue_position: null,
} satisfies Schema['ContentItem'];
const CLIP: Schema['LibraryItem'] = { ...ITEM, last_session_status: null };
const LIBRARY: Schema['LibraryItem'][] = [
  CLIP,
  {
    ...CLIP,
    id: 'clip-2',
    title: 'Morning news',
    status: 'pending',
    duration_ms: null,
    stage: 'converting',
    queue_position: null,
  },
  { ...CLIP, id: 'clip-3', title: 'Interview', status: 'failed', duration_ms: null },
];
const DETAIL = {
  ...ITEM,
  error_code: null,
  error_detail: null,
  has_video: false,
  keep_video: false,
  media_object_id: 'm-1',
  media_url: '/api/v1/media/m-1',
  peaks_url: '/api/v1/media/m-1/peaks',
} satisfies Schema['ContentDetail'];
const PEAKS = {
  version: 1,
  per_second: 10,
  scale: 100,
  peaks: Array.from({ length: 7600 }, (_, i) => 30 + Math.round(40 * Math.abs(Math.sin(i / 7)))),
};

const PASSAGE = { start_ms: 0, end_ms: 30_000 };
const TRANSCRIPT = {
  session_id: 'session-1',
  passage: PASSAGE,
  media_url: '/api/v1/media/m-1',
  lines: [
    {
      index: 0,
      start_ms: 0,
      end_ms: 2000,
      words: [
        { index: 0, text: 'Cities', start_ms: 0, end_ms: 800, edited: true },
        { index: 1, text: 'plant', start_ms: 800, end_ms: 1400, edited: false },
        { index: 2, text: 'trees.', start_ms: 1400, end_ms: 2000, edited: false },
      ],
    },
    {
      index: 1,
      start_ms: 10_000,
      end_ms: 12_000,
      words: [{ index: 3, text: 'Again.', start_ms: 10_000, end_ms: 12_000, edited: false }],
    },
  ],
} satisfies Schema['TranscriptReview'];
const MARKS: Schema['Mark'][] = [
  {
    id: 'm-1',
    session_id: 'session-1',
    word_from: 1,
    word_to: 1,
    at_ms: 800,
    note: 'linking',
    source: 'dictation',
    status: 'suggested',
    tag: 'linking',
    created_at: '2026-10-23T00:00:00Z',
  },
  {
    id: 'm-2',
    session_id: 'session-1',
    word_from: 3,
    word_to: 3,
    at_ms: 10_000,
    note: null,
    source: 'manual',
    status: 'confirmed',
    tag: null,
    created_at: '2026-10-23T00:00:00Z',
  },
];
const SCORED = {
  id: 'attempt-1',
  session_id: 'session-1',
  status: 'submitted',
  scoring_status: 'scored',
  result: {
    accuracy: 67,
    counts: { correct: 2, spelling_slip: 0, wrong: 1, missing: 0, extra: 0 },
    items: [
      { index: 0, status: 'correct', word: 'Cities', typed: 'Cities' },
      { index: 1, status: 'wrong', word: 'plant', typed: 'plan' },
      { index: 2, status: 'correct', word: 'trees.', typed: 'trees.' },
    ],
  },
} satisfies Schema['DictationAttemptView'];

function blindAttempt(overrides: Partial<Schema['BlindAttempt']> = {}): Schema['BlindAttempt'] {
  return {
    id: 'a-1',
    session_id: 'session-1',
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

/** The Blind step as the API reports it, with `attempt` its latest attempt. */
function blindStep(attempt: Schema['BlindAttempt'] | null): Answers {
  return {
    '/sessions/session-1/blind': {
      json: {
        session_id: 'session-1',
        passage_start_ms: PASSAGE.start_ms,
        passage_end_ms: PASSAGE.end_ms,
        step_status: attempt?.status === 'submitted' ? 'done' : 'open',
        attempt,
      } satisfies Schema['BlindStep'],
    },
  };
}
const SUBMITTED = blindAttempt({
  id: 'gist-1',
  status: 'submitted',
  position_ms: PASSAGE.end_ms,
  listen_complete: true,
  finished_at: '2026-10-03T10:01:00Z',
  gist_text: 'Cities plant trees to cool the streets.',
});

/** A session at `done` steps of its plan, with the reads its open step makes. */
function session(
  entry: 'blind' | 'dictation' | 'both',
  done: number,
  answers: Answers = {},
  overrides = {},
): Answers {
  const s = sessionFixture({ entry, done, passage: PASSAGE, ...overrides });
  return {
    '/sessions/session-1': { json: s },
    '/sessions': { json: { items: [s], next_cursor: null } },
    '/sessions/session-1/transcript': { json: TRANSCRIPT },
    '/sessions/session-1/marks': { json: { marks: MARKS } },
    '/sessions/session-1/dictation/attempt': problem(404, 'attempt_not_found', 'No attempt.'),
    '/contents/clip-1': { json: DETAIL },
    '/cards': { json: { cards: [], remaining: 2, next_cursor: null } },
    '/sessions/session-1/cards/suggestions': {
      json: { suggestions: [] } satisfies Schema['CardSuggestions'],
    },
    ...answers,
  };
}

const GIST_GRADE = {
  status: 'ready',
  overall: 80,
  level: 'good',
  dimension_scores: { main_idea: 90, key_details: 70, accuracy: 80 },
  captured_count: 1,
  total_count: 2,
  gist: 'Cities plant trees to cool the streets. They clean the air. People like them.',
  feedback: 'You caught the main idea. Listen again for the second detail.',
  key_points: [
    { text: 'Trees cool streets', captured: true },
    { text: 'Trees clean the air', captured: false },
  ],
} satisfies Schema['GistFeedback'];

const ADMIN_JOBS = {
  lanes: [
    { lane: 'speech-interactive', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
    { lane: 'intake', waiting: 2, scheduled: 0, running: 1, oldest_wait_seconds: 40 },
    { lane: 'ai', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
    { lane: 'background', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
  ],
  failed: [
    {
      id: 12,
      lane: 'intake',
      name: 'content.convert_upload',
      attempts: 5,
      failed_at: '2026-10-08T09:30:00Z',
    },
  ],
} satisfies Schema['JobsOverview'];
const ADMIN_USAGE = {
  start_date: '2026-10-01',
  end_date: '2026-10-30',
  as_of: '2026-10-30T23:30:00Z',
  providers: [
    {
      provider: 'hosted',
      days: [
        {
          date: '2026-10-30',
          calls: 2,
          input_tokens: 300,
          output_tokens: 50,
          audio_seconds: 4,
          estimated_cost_usd: 0.25,
          estimated_calls: 1,
        },
      ],
      quotas: [
        {
          period: 'day',
          calls: 2,
          tokens: 350,
          audio_seconds: 4,
          limits: { calls: 10, tokens: 1000 },
        },
      ],
    },
  ],
} satisfies Schema['UsageOverview'];

const EXPORT_READY = {
  id: 'e1',
  status: 'ready',
  requested_at: '2026-10-04T09:00:00Z',
  ready_at: '2026-10-04T09:02:00Z',
  expires_at: '2026-10-11T09:02:00Z',
  archive_bytes: 3 * 2 ** 20,
  file_count: 1,
  download_url: '/api/v1/me/exports/e1/download',
} satisfies Schema['DataExport'];

async function signIn(page: Page, password: string) {
  await page.getByLabel('Email').fill('learner@example.com');
  await page.getByLabel('Password').fill(password);
  await page.getByLabel('Password').press('Enter');
}

const REVIEW_CARD = {
  id: 'review-card',
  session_id: 'session-1',
  slot: 1,
  mark_id: null,
  written_form: 'could have',
  heard_form: 'kuduv',
  at_ms: 11000,
  content_id: 'clip-1',
  source_url: '/contents/clip-1?at_ms=11000',
  audio_status: 'ready',
  created_at: '2026-10-26T10:00:00Z',
} satisfies Schema['Card'];
const REVIEW_ANSWERS: Answers = {
  '/cards': {
    json: { cards: [REVIEW_CARD], next_cursor: null, remaining: null } satisfies Schema['CardList'],
  },
  '/cards/review-card/reviews': { json: { reviews: [] } satisfies Schema['ReviewHistory'] },
};

export const STATES: ScanState[] = [
  ...(['pending', 'failed', 'unavailable'] as const).map((status): ScanState => ({
    name: `saved cards audio ${status}`,
    path: '/cards',
    signedIn: true,
    answers: {
      ...REVIEW_ANSWERS,
      '/cards': {
        json: {
          cards: [{ ...REVIEW_CARD, audio_status: status }],
          next_cursor: null,
        } satisfies Schema['CardList'],
      },
    },
    ready: (page) => page.getByRole('button', { name: 'Play snippet' }),
  })),
  {
    name: 'saved cards result stored',
    path: '/cards',
    signedIn: true,
    answers: {
      ...REVIEW_ANSWERS,
      'POST /cards/review-card/reviews': {
        status: 201,
        json: {
          id: 'review-1',
          card_id: REVIEW_CARD.id,
          result: 'heard',
          reviewed_at: REVIEW_CARD.created_at,
        } satisfies Schema['CardReview'],
      },
    },
    act: async (page) => {
      await page.locator('audio').dispatchEvent('ended');
      await page.getByRole('button', { name: 'Reveal forms' }).click();
      await page.getByRole('button', { name: 'Heard', exact: true }).click();
    },
    ready: (page) => page.getByText('Saved: heard'),
  },
  {
    name: 'saved cards result failed',
    path: '/cards',
    signedIn: true,
    alert: true,
    answers: {
      ...REVIEW_ANSWERS,
      'POST /cards/review-card/reviews': problem(503, 'unavailable', 'Please try saving again.'),
    },
    act: async (page) => {
      await page.locator('audio').dispatchEvent('ended');
      await page.getByRole('button', { name: 'Reveal forms' }).click();
      await page.getByRole('button', { name: 'Heard', exact: true }).click();
    },
    ready: (page) => page.getByRole('alert'),
  },
  {
    name: 'saved cards empty',
    path: '/cards',
    signedIn: true,
    answers: { '/cards': { json: { cards: [], next_cursor: null } } },
    ready: (page) => page.getByText(/No saved cards yet/),
  },
  {
    name: 'saved cards hidden',
    path: '/cards',
    signedIn: true,
    answers: REVIEW_ANSWERS,
    ready: (page) => page.getByRole('button', { name: 'Reveal forms' }),
  },
  {
    name: 'saved cards revealed',
    path: '/cards',
    signedIn: true,
    answers: REVIEW_ANSWERS,
    act: async (page) => {
      await page.locator('audio').dispatchEvent('ended');
      await page.getByRole('button', { name: 'Reveal forms' }).click();
    },
    ready: (page) => page.getByRole('group', { name: 'How did you hear it?' }),
  },
  {
    name: 'saved marks empty',
    path: '/marks',
    signedIn: true,
    answers: { '/marks': { json: { marks: [], next_cursor: null } } },
    ready: (page) => page.getByText('No saved marks yet.'),
  },
  {
    name: 'saved marks list',
    path: '/marks',
    signedIn: true,
    answers: {
      '/marks': {
        json: {
          marks: [
            {
              id: 'mark-1',
              session_id: 'session-1',
              content_id: 'clip-1',
              word_from: 0,
              word_to: 1,
              at_ms: 11000,
              source: 'manual',
              status: 'confirmed',
              tag: null,
              note: 'Listen to the linked sounds',
              created_at: REVIEW_CARD.created_at,
              source_url: REVIEW_CARD.source_url,
            },
          ],
          next_cursor: null,
        } satisfies Schema['SavedMarkList'],
      },
    },
    ready: (page) => page.getByRole('link', { name: 'Open source at 11.0 seconds' }),
  },
  // Signed out.
  { name: 'sign-in', path: '/sign-in', ready: heading('Sign in') },
  {
    name: 'sign-in refused',
    alert: true,
    path: '/sign-in',
    answers: { '/auth/login': problem(401, 'invalid_credentials', 'Email or password is wrong.') },
    act: (page) => signIn(page, 'wrong horse'),
    ready: (page) => page.getByRole('alert'),
  },
  {
    name: 'sign-in paused',
    alert: true,
    path: '/sign-in',
    answers: {
      '/auth/login': () =>
        problem(429, 'account_locked', 'Too many failed sign-in attempts.', {
          locked_until: new Date(Date.now() + 10 * 60_000).toISOString(),
        }),
    },
    act: (page) => signIn(page, 'wrong horse'),
    ready: (page) => page.getByRole('alert').filter({ hasText: 'Sign-in is paused' }),
  },
  { name: 'register', path: '/register', ready: heading('Create your account') },
  {
    name: 'register field errors',
    alert: true,
    path: '/register',
    act: (page) => page.getByRole('button', { name: 'Create account' }).click(),
    ready: (page) => page.locator('[aria-invalid="true"]').first(),
  },
  { name: 'forgot password', path: '/forgot-password', ready: heading('Reset your password') },
  {
    name: 'forgot password sent',
    path: '/forgot-password',
    answers: { 'POST /auth/password-reset': { status: 202, json: { detail: 'Sent.' } } },
    act: async (page) => {
      await page.getByLabel('Email').fill('learner@example.com');
      await page.getByLabel('Email').press('Enter');
    },
    ready: (page) => page.getByRole('status').filter({ hasText: /./ }),
  },
  {
    name: 'reset password',
    path: '/reset-password#token=abc',
    ready: (page) => page.getByLabel('New password'),
  },
  {
    name: 'reset link incomplete',
    alert: true,
    path: '/reset-password',
    ready: (page) => page.getByRole('alert').filter({ hasText: 'incomplete' }),
  },
  {
    name: 'account deleted',
    path: '/account-deleted?until=2026-11-01T00%3A00%3A00Z',
    ready: heading('Your account is deleted'),
  },
  // The text itself, not only its title: the title also heads the "not available" error.
  { name: 'terms', path: '/terms', ready: (page) => page.getByText('Version terms-2026-1') },
  { name: 'privacy', path: '/privacy', ready: (page) => page.getByText('Version privacy-2026-1') },
  {
    name: 'voice consent',
    path: '/voice-consent',
    ready: (page) => page.getByText('Version voice-2026-1'),
  },
  {
    name: 'google error',
    alert: true,
    path: '/auth/google-error?reason=failed&intent=login',
    ready: heading(/Google/),
  },
  { name: 'page not found', path: '/no-such-page', ready: heading('Page not found') },

  // Library and intake.
  {
    name: 'library empty',
    path: '/library',
    signedIn: true,
    ready: heading('Add your first clip'),
  },
  {
    name: 'library with clips and plans',
    path: '/library',
    signedIn: true,
    answers: {
      '/library/contents': { json: { items: LIBRARY, next_cursor: null } },
      ...session('blind', 0),
      '/sessions/session-1': problem(404, 'not_found', 'unused'),
    },
    ready: (page) => page.getByRole('region', { name: 'Your plans' }),
  },
  { name: 'add clip', path: '/library/add', signedIn: true, ready: heading('Add a clip') },
  {
    name: 'add clip daily limit reached',
    path: '/library/add',
    signedIn: true,
    answers: {
      '/uploads/usage': {
        json: {
          used_bytes: 0,
          quota_bytes: 2048 * 2 ** 20,
          max_file_bytes: 500 * 2 ** 20,
          daily_audio: {
            used_seconds: 7200,
            limit_seconds: 7200,
            clips_in_progress: 0,
            reserved_seconds: 0,
            can_add: false,
            resets_at: '2030-01-01T00:00:00Z',
          },
        },
      },
    },
    ready: heading('Add a clip'),
  },
  {
    name: 'clip ready',
    path: '/contents/clip-1',
    signedIn: true,
    answers: { '/contents/clip-1': { json: DETAIL } },
    ready: heading(CLIP.title),
  },
  {
    name: 'clip converting',
    path: '/contents/clip-2',
    signedIn: true,
    answers: {
      '/contents/clip-2': {
        json: {
          ...DETAIL,
          id: 'clip-2',
          title: 'Morning news',
          status: 'pending',
          duration_ms: null,
          stage: 'converting',
          media_url: null,
          peaks_url: null,
        } satisfies Schema['ContentDetail'],
      },
    },
    ready: (page) => page.getByRole('status').filter({ hasText: /./ }).first(),
  },
  {
    name: 'clip removed copy',
    alert: true,
    path: '/contents/clip-4',
    signedIn: true,
    answers: {
      '/contents/clip-4': problem(410, 'duplicate_upload', 'You already have this clip.', {
        existing_content_id: 'clip-1',
        existing_title: CLIP.title,
      }),
    },
    ready: heading('You already have this clip'),
  },
  {
    name: 'clip not found',
    alert: true,
    path: '/contents/missing',
    signedIn: true,
    answers: { '/contents/missing': problem(404, 'not_found', 'Not found.') },
    ready: heading('We could not find this'),
  },
  {
    name: 'start plan',
    path: '/contents/clip-1/plan',
    signedIn: true,
    answers: { '/contents/clip-1': { json: DETAIL }, '/media/m-1/peaks': { json: PEAKS } },
    ready: heading('Start a plan'),
  },
  {
    name: 'start plan part of clip',
    path: '/contents/clip-1/plan',
    signedIn: true,
    answers: { '/contents/clip-1': { json: DETAIL }, '/media/m-1/peaks': { json: PEAKS } },
    act: (page) => page.getByRole('radio', { name: /A part of it/ }).check(),
    ready: (page) => page.getByRole('slider').first(),
  },

  // Account.
  { name: 'settings', path: '/settings', signedIn: true, ready: heading('Settings') },
  {
    name: 'settings export ready',
    path: '/settings',
    signedIn: true,
    answers: { '/me/exports/latest': { json: { export: EXPORT_READY } } },
    ready: (page) => page.getByRole('link', { name: /Download/ }),
  },
  {
    name: 'delete account',
    path: '/settings/delete-account',
    signedIn: true,
    answers: {
      '/me/deletion-summary': {
        json: { clips: 2, practice_sessions: 4, cards: 1, recordings: 0 },
      },
    },
    ready: heading('Delete your account'),
  },
  {
    name: 'consent owed',
    path: '/library',
    signedIn: true,
    answers: { '/me': { json: { ...LEARNER, consents_required: ['terms', 'privacy'] } } },
    ready: heading(/We updated our/),
  },

  // Admin.
  {
    name: 'admin jobs',
    path: '/admin/jobs',
    signedIn: true,
    answers: { '/admin/jobs': { json: ADMIN_JOBS } },
    ready: (page) => page.getByRole('button', { name: /Retry/ }).first(),
  },
  {
    name: 'admin usage',
    path: '/admin/usage',
    signedIn: true,
    answers: { '/admin/usage': { json: ADMIN_USAGE } },
    ready: heading(/usage/i),
  },

  // A practice session at each step.
  {
    name: 'blind ready to start',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 0, {
      ...blindStep(null),
    }),
    ready: (page) => page.getByRole('region', { name: 'Blind' }),
  },
  {
    name: 'blind gist form',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 0, {
      ...blindStep(blindAttempt({ position_ms: 30_000, listen_complete: true })),
    }),
    ready: (page) => page.getByRole('textbox').first(),
  },
  {
    name: 'blind attempt ended',
    alert: true,
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 0, {
      ...blindStep(
        blindAttempt({ status: 'voided', void_reason: 'left_page', position_ms: 2_000 }),
      ),
    }),
    ready: (page) => page.getByRole('region', { name: 'Blind' }),
  },
  {
    name: 'plan sheet',
    path: '/sessions/session-1',
    signedIn: true,
    only: 'narrow',
    answers: session('blind', 0, {
      ...blindStep(null),
    }),
    act: (page) => page.getByRole('button', { name: 'Plan', exact: true }).click(),
    ready: (page) => page.getByRole('dialog', { name: 'Your plan' }),
  },
  {
    name: 'dictation typing',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('dictation', 0, {
      '/sessions/session-1/dictation/attempts': {
        json: {
          id: 'attempt-1',
          session_id: 'session-1',
          status: 'active',
          started_at: '2026-10-03T10:00:00Z',
          resumed: true,
          draft_text: 'Cities plan',
          draft_version: 1,
          draft_updated_at: '2026-10-03T10:00:00Z',
          passage: PASSAGE,
          media_url: '/api/v1/media/m-1',
        },
      },
    }),
    ready: (page) => page.getByRole('button', { name: 'Submit for scoring' }),
  },
  {
    name: 'dictation scored beside transcript',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('dictation', 1, {
      '/sessions/session-1/dictation/attempt': { json: SCORED },
      '/dictation/attempts/attempt-1/marks': { json: { marks: [] } },
    }),
    ready: (page) => page.getByRole('button', { name: /Correct reference word/ }).first(),
  },
  {
    name: 'transcript with marks',
    path: '/sessions/session-1',
    signedIn: true,
    // Dictation entry, so the page has no gist feedback (#70's panel).
    answers: session('dictation', 1, {
      '/sessions/session-1/dictation/attempt': { json: SCORED },
      '/dictation/attempts/attempt-1/marks': { json: { marks: [] } },
    }),
    ready: (page) => page.getByRole('list', { name: 'Your marks' }),
  },
  {
    name: 'transcript mark editor',
    path: '/sessions/session-1',
    signedIn: true,
    // Dictation entry, so the page has no gist feedback (#70's panel).
    answers: session('dictation', 1, {
      '/sessions/session-1/dictation/attempt': { json: SCORED },
      '/dictation/attempts/attempt-1/marks': { json: { marks: [] } },
    }),
    act: (page) =>
      page
        .getByRole('list', { name: 'Your marks' })
        .getByRole('button', { name: /^Edit note/ })
        .first()
        .click(),
    ready: (page) => page.getByRole('textbox', { name: /note/i }),
  },
  {
    name: 'skip card dialog',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('dictation', 2),
    act: (page) => page.getByRole('button', { name: 'Skip Card' }).click(),
    ready: (page) => page.getByRole('dialog', { name: 'Skip Card?' }),
  },
  {
    name: 'plan finished',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('dictation', 4, {}, {}),
    ready: (page) => page.getByText(/All 4 steps finished/),
  },

  // Screens other open stories are changing: scanned, tracked there.
  {
    name: 'blind gist feedback beside transcript',
    owner: `${ISSUE}/70`,
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 1, {
      ...blindStep(SUBMITTED),
      '/gists/gist-1/grade': { json: GIST_GRADE },
    }),
    ready: (page) => page.getByText(GIST_GRADE.feedback),
  },
  {
    name: 'blind gist feedback before dictation',
    owner: `${ISSUE}/70`,
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('both', 0, {
      ...blindStep(blindAttempt({ position_ms: 30_000, listen_complete: true })),
      'POST /blind/attempts/a-1/gist': {
        status: 201,
        json: {
          attempt: blindAttempt({ status: 'submitted', listen_complete: true }),
          open_step: 'dictation',
          session_version: 1,
        } satisfies Schema['GistSubmitted'],
      },
      '/gists/a-1/grade': { json: GIST_GRADE },
    }),
    act: async (page) => {
      await page.getByRole('textbox').first().fill(GIST_GRADE.gist);
      await page.getByRole('button', { name: /Submit/ }).click();
    },
    ready: (page) => page.getByText(/You captured 1 of 2 key points/),
  },
  {
    name: 'card',
    owner: `${ISSUE}/73`,
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 2),
    ready: (page) => page.getByRole('button', { name: 'Skip Card' }),
  },
  {
    name: 'card suggested phrases',
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 2, {
      '/sessions/session-1/cards/suggestions': {
        json: {
          suggestions: [
            { mark_id: 'm-1', phrase: 'plant', suggested: true, reasons: ['linking'] },
            { mark_id: 'm-2', phrase: 'trees', suggested: false, reasons: [] },
          ],
        } satisfies Schema['CardSuggestions'],
      },
    }),
    act: async (page) => {
      await page.getByRole('combobox', { name: 'Marked phrase' }).selectOption('m-1');
    },
    ready: (page) => page.getByText('Suggested: tagged linking.'),
  },
  {
    name: 'shadow segment',
    owner: `${ISSUE}/79`,
    path: '/sessions/session-1',
    signedIn: true,
    answers: session('blind', 3, {
      '/sessions/session-1/shadow/segment': {
        json: {
          session_id: 'session-1',
          start_ms: 0,
          end_ms: 30_000,
          chosen_by: 'system',
          mark_count: 2,
          locked_at: null,
        } satisfies Schema['Segment'],
      },
      '/sessions/session-1/shadow/rounds': {
        json: {
          segment: {
            session_id: 'session-1',
            start_ms: 0,
            end_ms: 30_000,
            chosen_by: 'system',
            mark_count: 2,
            locked_at: null,
          },
          current: null,
          rounds: [],
        } satisfies Schema['Rounds'],
      },
      '/media/m-1/peaks': { json: PEAKS },
    }),
    ready: (page) => page.getByRole('heading', { name: 'Your Shadow segment' }),
  },
];

// #78's recovery and consent states share the existing owned session fixture.
const shadowReadiness = STATES.find((state) => state.name === 'shadow segment')!;
STATES.push(
  {
    ...shadowReadiness,
    name: 'shadow microphone denied',
    owner: undefined,
    act: async (page) => {
      await page.evaluate(() => {
        navigator.mediaDevices.getUserMedia = async () => {
          throw new DOMException('Permission denied', 'NotAllowedError');
        };
      });
      await page.getByRole('button', { name: 'Check microphone' }).click();
    },
    ready: (page) => page.getByText(/Microphone access was denied/),
  },
  {
    ...shadowReadiness,
    name: 'shadow voice consent accepted',
    owner: undefined,
    answers: {
      ...shadowReadiness.answers,
      '/me/consents': {
        json: {
          current: {
            terms: 'terms-2026-1',
            privacy: 'privacy-2026-1',
            voice_recording: 'voice-2026-1',
          },
          consents: [
            {
              kind: 'voice_recording',
              version: 'voice-2026-1',
              current: true,
              granted_at: '2026-10-26T10:00:00Z',
              withdrawn_at: null,
            },
          ],
        } satisfies Schema['Consents'],
      },
    },
    ready: (page) => page.getByText(/You agreed to this version/),
  },
  {
    ...shadowReadiness,
    name: 'shadow legal text unavailable',
    owner: undefined,
    answers: {
      ...shadowReadiness.answers,
      '/auth/consent-versions': {
        json: {
          terms: 'terms-2026-1',
          privacy: 'privacy-2026-1',
          voice_recording: 'voice-future',
        } satisfies Schema['ConsentVersions'],
      },
    },
    ready: (page) => page.getByText(/current voice consent text is unavailable/),
  },
  {
    ...shadowReadiness,
    name: 'shadow consent read failed',
    owner: undefined,
    alert: true,
    answers: {
      ...shadowReadiness.answers,
      '/me/consents': problem(503, 'unavailable', 'Consent records are temporarily unavailable.'),
    },
    ready: (page) => page.getByText('Consent records are temporarily unavailable.'),
  },
);
