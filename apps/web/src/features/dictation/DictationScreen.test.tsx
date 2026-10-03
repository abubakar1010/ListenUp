import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes, type Call } from '../session/testApi';
import { draftStorageKey, type DictationAttempt } from './api';

// A plan of both with Blind done: Dictation is open. Passage 02:10 to 04:40 (150 s).
const SESSION = sessionFixture({ entry: 'both', done: 1 });
const ATTEMPT_PATH = `/sessions/${SESSION.id}/dictation/attempts`;
const DRAFT_PATH = '/dictation/attempts/attempt-1/draft';

function attempt(overrides: Partial<DictationAttempt> = {}): DictationAttempt {
  return {
    id: 'attempt-1',
    session_id: SESSION.id,
    status: 'active',
    started_at: '2026-10-03T10:00:00Z',
    resumed: true,
    draft_text: 'So the first thing',
    draft_version: 3,
    draft_updated_at: '2026-10-03T10:40:00Z',
    passage: { start_ms: 130_000, end_ms: 280_000 },
    media_url: '/api/v1/media/media-1',
    ...overrides,
  };
}

let clock = 0;
let play: ReturnType<typeof vi.fn<(this: HTMLMediaElement) => Promise<void>>>;
let pause: ReturnType<typeof vi.fn<(this: HTMLMediaElement) => void>>;

beforeEach(() => {
  localStorage.clear();
  clock = 0;
  // jsdom has no media playback: the element's time and play state are faked here.
  play = vi.fn<(this: HTMLMediaElement) => Promise<void>>(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: false, configurable: true });
    this.dispatchEvent(new Event('play'));
    return Promise.resolve();
  });
  pause = vi.fn<(this: HTMLMediaElement) => void>(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: true, configurable: true });
    this.dispatchEvent(new Event('pause'));
  });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play);
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pause);
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get: () => clock,
    set: (value: number) => {
      clock = value;
    },
  });
});

afterEach(() => vi.restoreAllMocks());

function renderDictation(routes: Parameters<typeof mockRoutes>[0] = {}) {
  const mocked = mockRoutes({
    [`GET /sessions/${SESSION.id}`]: jsonResponse(200, SESSION),
    [`POST ${ATTEMPT_PATH}`]: jsonResponse(200, attempt()),
    [`PUT ${DRAFT_PATH}`]: jsonResponse(200, {
      draft_version: 4,
      updated_at: '2026-10-03T10:51:00Z',
    }),
    ...routes,
  });
  renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: `/sessions/${SESSION.id}` },
  );
  return mocked;
}

async function textArea() {
  return screen.findByRole('textbox', { name: 'Your text' });
}

function audio(): HTMLAudioElement {
  const element = document.querySelector('audio');
  if (!element) throw new Error('no audio element');
  return element;
}

function loadAudio() {
  act(() => {
    audio().dispatchEvent(new Event('loadedmetadata'));
  });
}

const puts = (calls: Call[]) => calls.filter((call) => call.method === 'PUT');

test('Dictation opens with the player, one text area and the saved draft', async () => {
  const { calls } = renderDictation();

  const text = await textArea();
  expect(text).toHaveValue('So the first thing');
  expect(text).toHaveFocus();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    'Dictation: Why cities plant street trees',
  );
  const player = screen.getByRole('region', { name: 'Player' });
  for (const name of ['Back 5 seconds', 'Play', 'Replay segment']) {
    expect(within(player).getByRole('button', { name })).toBeInTheDocument();
  }
  const speed = within(player).getByRole('combobox', { name: 'Speed' });
  expect(
    within(speed)
      .getAllByRole('option')
      .map((o) => o.textContent),
  ).toEqual(['1x', '0.9x', '0.75x']);
  expect(speed).toHaveValue('1');
  expect(within(player).getByRole('slider', { name: 'Seek' })).toHaveAttribute('max', '150000');
  expect(audio()).toHaveAttribute('src', '/api/v1/media/media-1');
  expect(screen.getAllByText('Draft saved').length).toBeGreaterThan(0);
  expect(screen.getByText('spell', { exact: false })).toHaveTextContent('4 words');
  const requests = calls.filter((call) => call.path !== '/health'); // the CSRF cookie
  expect(requests.map((call) => `${call.method} ${call.path}`)).toEqual([
    `GET /sessions/${SESSION.id}`,
    `POST ${ATTEMPT_PATH}`,
  ]);
});

test('the text area offers no spell-check, autocomplete, autocorrect or capitals', async () => {
  renderDictation();

  const text = await textArea();

  expect(text).toHaveAttribute('spellcheck', 'false');
  expect(text).toHaveAttribute('autocomplete', 'off');
  expect(text).toHaveAttribute('autocorrect', 'off');
  expect(text).toHaveAttribute('autocapitalize', 'off');
  expect(text).toHaveAttribute('maxlength', '20000');
  expect(screen.getAllByRole('textbox')).toHaveLength(1);
});

test('the transcript is never requested or shown', async () => {
  const { calls } = renderDictation();
  await textArea();
  loadAudio();

  expect(calls.some((call) => /transcript/i.test(call.path))).toBe(false);
  // The only "Transcript" on the page is the name of the next step in the plan.
  const work = screen.getByRole('region', { name: 'Dictation' });
  expect(within(work).queryByText(/transcript/i)).not.toBeInTheDocument();
});

test('typing is saved 2 s after the last key, on the version last seen', async () => {
  const { calls } = renderDictation();
  const text = await textArea();

  fireEvent.change(text, { target: { value: 'So the first thing you notice' } });
  expect(screen.getAllByText('Saving…').length).toBeGreaterThan(0);
  expect(puts(calls)).toHaveLength(0);

  await waitFor(() => expect(puts(calls)).toHaveLength(1), { timeout: 4000 });
  expect(puts(calls)[0]!.body).toEqual({
    draft_text: 'So the first thing you notice',
    draft_version: 3,
  });
  expect((await screen.findAllByText(/^Draft saved \d\d:\d\d$/)).length).toBeGreaterThan(0);
});

test('leaving the text area saves at once', async () => {
  const { calls } = renderDictation();
  const text = await textArea();

  fireEvent.change(text, { target: { value: 'typed' } });
  fireEvent.blur(text);

  await waitFor(() => expect(puts(calls)).toHaveLength(1));
});

test('text typed before a reload comes back from this device and is saved', async () => {
  localStorage.setItem(
    draftStorageKey('attempt-1'),
    JSON.stringify({ value: 'So the first thing you notice is the shade', baseVersion: 3 }),
  );
  const { calls } = renderDictation();

  expect(await textArea()).toHaveValue('So the first thing you notice is the shade');
  expect(screen.getByText(/We restored text you typed earlier/)).toBeInTheDocument();
  await waitFor(() => expect(puts(calls)).toHaveLength(1));
  expect(puts(calls)[0]!.body).toMatchObject({ draft_version: 3 });
});

test('a draft saved in another tab is shown as a conflict, not overwritten', async () => {
  const { calls } = renderDictation({
    [`PUT ${DRAFT_PATH}`]: (call) =>
      (call.body as { draft_version: number }).draft_version === 3
        ? problem(409, 'draft_conflict', 'Your text was changed in another tab.', {
            draft_text: 'Typed in the other tab',
            draft_version: 5,
            updated_at: '2026-10-03T10:50:00Z',
          })
        : jsonResponse(200, { draft_version: 6, updated_at: '2026-10-03T10:52:00Z' }),
  });
  const text = await textArea();
  fireEvent.change(text, { target: { value: 'Typed in this tab' } });
  fireEvent.blur(text);

  const panel = await screen.findByRole('alert');
  expect(panel).toHaveTextContent('Your text was changed in another tab');
  expect(panel).toHaveTextContent('Typed in the other tab');
  expect(text).toHaveValue('Typed in this tab');

  fireEvent.click(within(panel).getByRole('button', { name: 'Keep the text on this page' }));

  await waitFor(() => expect(puts(calls)).toHaveLength(2));
  expect(puts(calls)[1]!.body).toEqual({ draft_text: 'Typed in this tab', draft_version: 5 });
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});

test('the other version can replace the text on this page', async () => {
  renderDictation({
    [`PUT ${DRAFT_PATH}`]: problem(409, 'draft_conflict', 'Changed elsewhere.', {
      draft_text: 'Typed in the other tab',
      draft_version: 5,
      updated_at: '2026-10-03T10:50:00Z',
    }),
  });
  const text = await textArea();
  fireEvent.change(text, { target: { value: 'Typed in this tab' } });
  fireEvent.blur(text);

  fireEvent.click(await screen.findByRole('button', { name: 'Use the other version' }));

  expect(text).toHaveValue('Typed in the other tab');
  expect(localStorage.getItem(draftStorageKey('attempt-1'))).toBeNull();
});

test('a lost connection keeps the text on this device', async () => {
  const { spy } = renderDictation();
  const text = await textArea();
  spy.mockRejectedValue(new TypeError('Failed to fetch'));

  fireEvent.change(text, { target: { value: 'typed offline' } });
  fireEvent.blur(text);

  expect((await screen.findAllByText('Offline. Saved on this device.')).length).toBeGreaterThan(0);
  expect(JSON.parse(localStorage.getItem(draftStorageKey('attempt-1'))!)).toEqual({
    value: 'typed offline',
    baseVersion: 3,
  });
});

test('a locked Dictation step shows why', async () => {
  renderDictation({
    [`POST ${ATTEMPT_PATH}`]: problem(409, 'step_locked', 'The dictation step is locked.', {
      step: 'dictation',
      open_step: 'blind',
    }),
  });

  expect(await screen.findByRole('alert')).toHaveTextContent('The dictation step is locked.');
});

describe('the player', () => {
  test('starts at the passage and stops at its end', async () => {
    renderDictation();
    await textArea();
    loadAudio();
    expect(clock).toBe(130);

    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(play).toHaveBeenCalled();
    clock = 280.2;
    act(() => {
      audio().dispatchEvent(new Event('timeupdate'));
    });

    expect(pause).toHaveBeenCalled();
    expect(clock).toBe(280);
    expect(screen.getByText('02:30 / 02:30')).toBeInTheDocument();
  });

  test('seeking stays inside the passage', async () => {
    renderDictation();
    await textArea();
    loadAudio();

    fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), {
      target: { value: '48000' },
    });

    expect(clock).toBe(178);
    expect(screen.getByText('00:48 / 02:30')).toBeInTheDocument();
    expect(screen.getByText(/Segment 7 of 19/)).toBeInTheDocument();
  });

  test('replays are unlimited and counted', async () => {
    renderDictation();
    await textArea();
    loadAudio();
    const replay = screen.getByRole('button', { name: 'Replay segment' });

    for (let i = 0; i < 12; i += 1) fireEvent.click(replay);

    expect(screen.getByText('12')).toBeInTheDocument();
    expect(play).toHaveBeenCalledTimes(12);
  });

  test('a slower speed is one choice away', async () => {
    renderDictation();
    await textArea();
    loadAudio();

    fireEvent.change(screen.getByRole('combobox', { name: 'Speed' }), {
      target: { value: '0.75' },
    });

    expect(audio().playbackRate).toBe(0.75);
  });

  test('keys work while typing: Esc plays, Ctrl+Alt+J goes back 5 s', async () => {
    renderDictation();
    const text = await textArea();
    loadAudio();
    fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), {
      target: { value: '20000' },
    });

    fireEvent.keyDown(text, { key: 'Escape', code: 'Escape' });
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(text, { key: 'j', code: 'KeyJ', ctrlKey: true, altKey: true });
    expect(clock).toBe(145);
    fireEvent.keyDown(text, { key: 'j', code: 'KeyJ' });
    expect(clock).toBe(145); // a plain J is text
  });

  test('outside the text area, single keys work', async () => {
    renderDictation();
    await textArea();
    loadAudio();
    (document.activeElement as HTMLElement).blur();

    fireEvent.keyDown(document.body, { key: ' ', code: 'Space' });
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: '[', code: 'BracketLeft' });
    expect(audio().playbackRate).toBe(0.9);
  });
});
