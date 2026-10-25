import { act, fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { RESULT } from '../dictation/fixtures';
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
    [`GET /sessions/${SESSION.id}/marks`]: jsonResponse(200, { marks: [] }),
    [`GET /sessions/${SESSION.id}/dictation/attempt`]: problem(
      404,
      'attempt_not_found',
      'No Dictation attempt.',
    ),
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

test('keeps_the_completed_Dictation_result_beside_the_ready_transcript', async () => {
  renderReview({
    [`GET /sessions/${SESSION.id}/dictation/attempt`]: jsonResponse(200, {
      id: 'attempt-1',
      session_id: SESSION.id,
      status: 'submitted',
      scoring_status: 'scored',
      result: RESULT,
    }),
  });
  await ready();
  expect(await screen.findByText('90%')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Word by word' })).toHaveTextContent('summer.');
  expect(screen.getByRole('button', { name: 'Jump to Hello' })).toBeEnabled();
});

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

test('shows_learner_edits_and_removed_words_with_original_audio_targets', async () => {
  renderReview({
    [`GET ${PATH}`]: jsonResponse(200, {
      ...DATA,
      lines: [
        {
          ...DATA.lines[0],
          words: [
            { ...DATA.lines[0].words[0], text: 'Greetings', edited: true },
            { ...DATA.lines[0].words[1], text: '', edited: true },
          ],
        },
        DATA.lines[1],
      ],
    }),
  });
  const changed = await screen.findByRole('button', { name: 'Jump to Greetings (edited)' });
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  expect(within(changed).getByText('Edited')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Jump to Hello' })).not.toBeInTheDocument();
  fireEvent.click(changed);
  expect(audioTime).toBe(131);
  const removed = screen.getByRole('button', { name: 'Jump to removed word (edited)' });
  expect(removed).toHaveTextContent('(removed word)');
  expect(within(removed).getByText('Edited')).toBeVisible();
  fireEvent.click(removed);
  expect(audioTime).toBe(132);
  expect(
    within(screen.getByRole('button', { name: 'Jump to Again.' })).queryByText('Edited'),
  ).toBeNull();
});

test('seek_sets_exact_target_without_debounce_and_preserves_playback_state', async () => {
  renderReview();
  const audio = await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  vi.useFakeTimers();
  const seek = screen.getByRole('slider', { name: 'Seek' });
  fireEvent.change(seek, { target: { value: '10125' } });
  // Assert before advancing timers: application code must not debounce the seek
  // or round away fractional-second targets. Real media latency is a browser check.
  expect(audioTime).toBe(140.125);
  expect(audio.paused).toBe(false);
  expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  fireEvent.change(seek, { target: { value: '11250' } });
  expect(audioTime).toBe(141.25);
  expect(audio.paused).toBe(true);
  expect(play).toHaveBeenCalledOnce();
  expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled();
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
    fireEvent.click(
      screen.getByRole('button', {
        name: code === 'transcript_not_ready' ? 'Check now' : 'Try again',
      }),
    );
    expect(await screen.findByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
  },
);

test('the mark list and the keys sit in the side panel, after the transcript (#200)', async () => {
  renderReview();
  await ready();

  const work = screen.getByRole('region', { name: 'Transcript' });
  const side = screen.getByRole('complementary', { name: 'Side panel' });
  expect(within(side).getByRole('region', { name: 'Your marks' })).toBeInTheDocument();
  expect(within(side).getByText('Keyboard shortcuts')).toBeInTheDocument();
  expect(within(work).queryByRole('region', { name: 'Your marks' })).not.toBeInTheDocument();
  // The selection panel stays above the lines, where words are chosen.
  const panel = within(work).getByRole('region', { name: 'Mark words' });
  const lines = within(work).getByRole('list', { name: 'Transcript lines' });
  expect(panel.compareDocumentPosition(lines) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // Reading order: the transcript and Finish come before the side panel.
  expect(lines.compareDocumentPosition(side) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test('while the transcript is prepared the page says so, stays busy and fills in by itself', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let ready = false;
  renderReview({
    [`GET ${PATH}`]: () =>
      ready
        ? jsonResponse(200, DATA)
        : problem(409, 'transcript_not_ready', 'The passage transcript is not ready yet.'),
  });

  const waiting = await screen.findByRole('status', { name: 'Preparing your transcript…' });
  expect(waiting).toHaveAttribute('aria-busy', 'true');
  expect(waiting).toHaveTextContent('This page updates by itself when it is ready.');
  expect(screen.getByRole('button', { name: 'Check now' })).toBeInTheDocument();

  ready = true;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(await screen.findByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
  expect(screen.getByText('Your transcript is ready.')).toHaveAttribute('role', 'status');
});

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

test('finishing_Transcript_refreshes_the_plan_and_opens_Card', async () => {
  let finished = false;
  let resolve!: (response: Response) => void;
  renderReview({
    [`GET /sessions/${SESSION.id}`]: () =>
      jsonResponse(200, finished ? sessionFixture({ entry: 'dictation', done: 2 }) : SESSION),
    [`POST ${PATH}/complete`]: () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  });
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Finish Transcript' }));
  expect(await screen.findByRole('button', { name: 'Finishing Transcript…' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  await act(async () => {
    finished = true;
    resolve(new Response(null, { status: 204 }));
  });
  expect(
    await screen.findByRole('heading', { name: `Card: ${SESSION.content_title}` }),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Skip Card' })).toBeEnabled();
});

test('completion_failure_keeps_Transcript_and_allows_retry', async () => {
  renderReview({ [`POST ${PATH}/complete`]: problem(503, 'unavailable', 'Please try later.') });
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Finish Transcript' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Please try later.');
  expect(screen.getByRole('button', { name: 'Finish Transcript' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
});

test('completion_with_a_lost_response_reloads_the_persisted_plan_and_opens_Card', async () => {
  let finished = false;
  renderReview({
    [`GET /sessions/${SESSION.id}`]: () =>
      jsonResponse(200, finished ? sessionFixture({ entry: 'dictation', done: 2 }) : SESSION),
    [`POST ${PATH}/complete`]: () => {
      finished = true;
      throw new TypeError('Lost completion response');
    },
  });
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Finish Transcript' }));
  expect(
    await screen.findByRole('heading', { name: `Card: ${SESSION.content_title}` }),
  ).toBeInTheDocument();
});

test('repeated_finish_activation_during_a_request_sends_only_one_completion', async () => {
  let count = 0;
  let resolve!: (response: Response) => void;
  renderReview({
    [`POST ${PATH}/complete`]: () => {
      count += 1;
      return new Promise<Response>((r) => {
        resolve = r;
      });
    },
  });
  await ready();
  const finish = screen.getByRole('button', { name: 'Finish Transcript' });
  fireEvent.click(finish);
  fireEvent.click(finish);
  await act(async () => {});
  expect(count).toBe(1);
  const busy = await screen.findByRole('button', { name: 'Finishing Transcript…' });
  expect(busy).toHaveAccessibleDescription('Finishing Transcript. Please wait.');
  fireEvent.click(busy);
  expect(screen.getByText('Finishing Transcript. Please wait.')).toHaveFocus();
  expect(count).toBe(1);
  await act(async () => resolve(problem(503, 'unavailable', 'Please try later.')));
});

test('completion_retries_send_the_same_submission_key', async () => {
  const keys: (string | undefined)[] = [];
  renderReview({
    [`POST ${PATH}/complete`]: (call) => {
      keys.push(call.headers['Idempotency-Key']);
      return problem(503, 'unavailable', 'Please try later.');
    },
  });
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Finish Transcript' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Finish Transcript' }));
  await act(async () => {});
  expect(keys).toEqual([`transcript-${SESSION.id}`, `transcript-${SESSION.id}`]);
});

test.each(['blind', 'both'] as const)(
  'full gist grade beside Transcript on %s path',
  async (entry) => {
    renderReview({
      'GET /sessions/session-1': jsonResponse(
        200,
        sessionFixture({ entry, done: entry === 'both' ? 2 : 1 }),
      ),
      'GET /sessions/session-1/blind': jsonResponse(200, {
        attempt: { id: 'gist-1', status: 'submitted' },
      }),
      'GET /gists/gist-1/grade': jsonResponse(200, {
        status: 'ready',
        overall: 80,
        level: 'good',
        dimension_scores: { main_idea: 90 },
        captured_count: 1,
        total_count: 2,
        gist: 'I heard this gist.',
        feedback: 'Full written feedback.',
        key_points: [
          { text: 'Main point', captured: true },
          { text: 'Other point', captured: false },
        ],
      }),
    });
    await ready();
    const aside = screen.getByRole('complementary', { name: 'Side panel' });
    expect(await within(aside).findByText('I heard this gist.')).toBeInTheDocument();
    expect(within(aside).getByText('Full written feedback.')).toBeInTheDocument();
    expect(within(aside).getByText(/Missed: Other point/)).toBeInTheDocument();
    // The side panel holds the gist (#69) first, then the keys and the mark list (#200).
    const gist = within(aside).getByRole('region', { name: /gist/i });
    const marks = within(aside).getByRole('region', { name: 'Your marks' });
    expect(within(aside).getByText('Keyboard shortcuts')).toBeInTheDocument();
    expect(gist.compareDocumentPosition(marks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
);
