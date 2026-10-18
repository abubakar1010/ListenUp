import { act, fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes } from '../session/testApi';

const SESSION = sessionFixture({ entry: 'dictation', done: 1 });
const PATH = `/sessions/${SESSION.id}/transcript`;
const DATA = {
  session_id: SESSION.id,
  passage: SESSION.passage,
  media_url: '/api/v1/media/media-1',
  lines: [
    {
      index: 0,
      start_ms: 131000,
      end_ms: 133000,
      words: [
        { index: 0, text: 'Hello', start_ms: 131000, end_ms: 132000 },
        { index: 1, text: 'world.', start_ms: 132000, end_ms: 133000 },
      ],
    },
    {
      index: 1,
      start_ms: 140125,
      end_ms: 142000,
      words: [{ index: 2, text: 'Again.', start_ms: 140125, end_ms: 142000 }],
    },
  ],
};

let audioTime = 0;
let play: ReturnType<typeof vi.fn<(this: HTMLMediaElement) => Promise<void>>>;
let pause: ReturnType<typeof vi.fn<(this: HTMLMediaElement) => void>>;
beforeEach(() => {
  audioTime = 0;
  play = vi.fn(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: false, configurable: true });
    this.dispatchEvent(new Event('play'));
    this.dispatchEvent(new Event('playing'));
    return Promise.resolve();
  });
  pause = vi.fn(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: true, configurable: true });
    this.dispatchEvent(new Event('pause'));
  });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play);
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pause);
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get: () => audioTime,
    set: (value: number) => {
      audioTime = value;
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function renderReview(routes: Parameters<typeof mockRoutes>[0] = {}) {
  mockRoutes({
    [`GET /sessions/${SESSION.id}`]: jsonResponse(200, SESSION),
    [`GET ${PATH}`]: jsonResponse(200, DATA),
    ...routes,
  });
  return renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: `/sessions/${SESSION.id}` },
  );
}
async function ready() {
  await screen.findByRole('button', { name: 'Jump to Hello' });
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  return audio;
}
function current() {
  return document.querySelector('[aria-current="true"]');
}

test('highlights_current_line_at_boundaries_without_colour_or_focus_changes', async () => {
  renderReview();
  const audio = await ready();
  expect(current()).toBeNull();
  const word = screen.getByRole('button', { name: 'Jump to Hello' });
  word.focus();
  audioTime = 131;
  fireEvent.timeUpdate(audio);
  expect(current()).toHaveTextContent('Hello');
  expect(current()).toHaveTextContent('Current line');
  expect(current()).toHaveClass('border-l-4');
  audioTime = 139; // silence keeps the preceding line current for replay
  fireEvent.timeUpdate(audio);
  expect(current()).toHaveTextContent('Hello');
  audioTime = 140.125;
  fireEvent.timeUpdate(audio);
  expect(current()).toHaveTextContent('Again.');
  expect(word).toHaveFocus();
  audioTime = 280;
  fireEvent.timeUpdate(audio);
  expect(current()).toHaveTextContent('Again.');
  expect(screen.getByText('Entry locked')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Change entry' })).not.toBeInTheDocument();
});

test('replays_current_line_changes_speed_and_word_activation_jumps', async () => {
  renderReview();
  const audio = await ready();
  audioTime = 141;
  fireEvent.timeUpdate(audio);
  fireEvent.click(screen.getByRole('button', { name: 'Replay line' }));
  expect(audioTime).toBe(140.125);
  expect(play).toHaveBeenCalledOnce();
  expect(screen.getByText('1')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Speed' }), { target: { value: '0.75' } });
  expect(audio.playbackRate).toBe(0.75);
  expect(audio.preservesPitch).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Jump to world.' }));
  expect(audioTime).toBe(132);
  expect(current()).toHaveTextContent('Hello');
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  expect(pause).toHaveBeenCalled();
});

test('seek_resumes_within_300ms_at_the_controlled_media_boundary', async () => {
  renderReview();
  const audio = await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  vi.useFakeTimers();
  let resumedAt = -1;
  audio.addEventListener('playing', () => {
    resumedAt = performance.now();
  });
  audio.addEventListener('seeked', () => {
    if (!audio.paused) audio.dispatchEvent(new Event('playing'));
  });
  const start = performance.now();
  fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), { target: { value: '10000' } });
  expect(audioTime).toBe(140); // target is set immediately, without debounce
  act(() => {
    vi.advanceTimersByTime(299);
    fireEvent.seeked(audio);
  });
  expect(resumedAt - start).toBeGreaterThanOrEqual(0);
  expect(resumedAt - start).toBeLessThan(300);
  expect(audio.paused).toBe(false);
  // A boundary at 300 ms must not qualify as passing evidence.
  const delayed = performance.now();
  act(() => {
    vi.advanceTimersByTime(300);
    fireEvent.seeked(audio);
  });
  expect(resumedAt - delayed).not.toBeLessThan(300);
});

test('supports_player_shortcuts_without_hijacking_controls', async () => {
  renderReview();
  await ready();
  fireEvent.keyDown(document.body, { key: 'k', code: 'KeyK' });
  expect(play).toHaveBeenCalledOnce();
  fireEvent.keyDown(document.body, { key: 'r', code: 'KeyR' });
  expect(audioTime).toBe(131);
  fireEvent.keyDown(document.body, { key: '[', code: 'BracketLeft' });
  expect(screen.getByRole('combobox', { name: 'Speed' })).toHaveValue('0.9');
  fireEvent.keyDown(document.body, { key: ']', code: 'BracketRight' });
  expect(screen.getByRole('combobox', { name: 'Speed' })).toHaveValue('1');
  fireEvent.keyDown(document.body, { key: 'j', code: 'KeyJ' });
  expect(audioTime).toBe(130);
  const slider = screen.getByRole('slider', { name: 'Seek' });
  fireEvent.keyDown(slider, { key: ' ', code: 'Space' });
  expect(pause).not.toHaveBeenCalled();
  fireEvent.keyDown(document.body, { key: 'r', code: 'KeyR', ctrlKey: true });
  expect(audioTime).toBe(130);
  fireEvent.keyDown(document.body, { key: ' ', code: 'Space' });
  expect(pause).toHaveBeenCalledOnce();
  expect(screen.getByText(/Space or K/)).toBeInTheDocument();
});

test('shows_loading_and_empty_transcript', async () => {
  let resolve!: (response: Response) => void;
  renderReview({
    [`GET ${PATH}`]: () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  });
  expect(await screen.findByText('Opening your Transcript…')).toBeInTheDocument();
  await act(async () => resolve(jsonResponse(200, { ...DATA, lines: [] })));
  expect(await screen.findByText('No speech was found in this passage.')).toBeInTheDocument();
  fireEvent.loadedMetadata(document.querySelector('audio')!);
  expect(screen.getByRole('button', { name: 'Replay line' })).toBeDisabled();
  fireEvent.keyDown(document.body, { key: 'r', code: 'KeyR' });
  expect(play).not.toHaveBeenCalled(); // no sentence exists to replay
});

test.each(['transcript_not_ready', 'transcript_failed'])(
  'shows %s and refetches on retry',
  async (code) => {
    let attempts = 0;
    renderReview({
      [`GET ${PATH}`]: () =>
        ++attempts === 1 ? problem(409, code, 'Transcript unavailable.') : jsonResponse(200, DATA),
    });
    expect(
      await screen.findByText(
        code === 'transcript_not_ready'
          ? 'Preparing your transcript…'
          : 'The transcript could not be prepared.',
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
  },
);

test('shows_other_API_errors_and_media_errors', async () => {
  renderReview();
  const audio = await ready();
  fireEvent.error(audio);
  expect(within(screen.getByRole('alert')).getByText(/audio could not load/)).toBeInTheDocument();
});

test('generic_API_errors_use_ErrorPanel', async () => {
  let attempts = 0;
  renderReview({
    [`GET ${PATH}`]: () =>
      ++attempts === 1 ? problem(503, 'unavailable', 'Please try later.') : jsonResponse(200, DATA),
  });
  expect(await screen.findByRole('alert')).toHaveTextContent('Please try later.');
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
});

test('replay_in_leading_silence_starts_first_line_and_paused_seek_stays_paused', async () => {
  renderReview();
  const audio = await ready();
  audioTime = 129; // an external seek before this 130-second passage is corrected
  fireEvent.timeUpdate(audio);
  expect(audioTime).toBe(130);
  fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), { target: { value: '500' } });
  expect(audioTime).toBe(130.5);
  expect(play).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Replay line' }));
  expect(audioTime).toBe(131);
  expect(play).toHaveBeenCalledOnce();
  audioTime = 500;
  fireEvent.timeUpdate(audio);
  expect(audioTime).toBe(280);
  expect(audio.paused).toBe(true);
});
