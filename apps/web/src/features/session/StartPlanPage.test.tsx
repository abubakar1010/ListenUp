import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import type { ContentDetail } from '../content/useContent';
import { sessionFixture } from './fixtures';
import StartPlanPage from './StartPlanPage';
import { mockRoutes } from './testApi';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function clip(overrides: Partial<ContentDetail> = {}): ContentDetail {
  return {
    id: 'clip-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: 600_000,
    created_at: '2026-10-03T09:00:00Z',
    error_code: null,
    error_detail: null,
    has_video: false,
    keep_video: false,
    media_object_id: 'm-1',
    media_url: '/api/v1/media/m-1',
    peaks_url: '/api/v1/media/m-1/peaks',
    ...overrides,
  };
}

/** The conversion job's peaks: `silentS` seconds of room tone, then speech. */
function peaks(silentS: number, totalS: number) {
  const values = Array.from({ length: totalS * 10 }, (_, i) => (i < silentS * 10 ? 2 : 55));
  return jsonResponse(200, { version: 1, per_second: 10, scale: 100, peaks: values });
}

function routes(item: ContentDetail, silentS = 0) {
  return {
    'GET /contents/clip-1': jsonResponse(200, item),
    'GET /media/m-1/peaks': peaks(silentS, Math.ceil((item.duration_ms ?? 0) / 1000)),
  };
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/contents/:contentId/plan" element={<StartPlanPage />} />
      <Route path="/sessions/:sessionId" element={<h1>Session page</h1>} />
    </Routes>,
    { route: '/contents/clip-1/plan' },
  );
}

const startButton = () => screen.getByRole('button', { name: 'Start plan' });
const slider = (name: 'Passage start' | 'Passage end') => screen.getByRole('slider', { name });
const field = (name: 'Start' | 'End') => screen.getByRole('textbox', { name });

test('the whole clip and Blind are chosen first; Both gives 5 steps with Blind first', async () => {
  const { calls } = mockRoutes({
    ...routes(clip()),
    'POST /sessions': () => jsonResponse(201, sessionFixture({ id: 'new-1', entry: 'both' })),
  });
  renderPage();

  expect(await screen.findByRole('radio', { name: /Whole clip · 10:00/ })).toBeChecked();
  expect(screen.getByRole('status')).toHaveTextContent('10 minutes selected');
  expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  const blind = screen.getByRole('checkbox', { name: /Blind/ });
  const dictation = screen.getByRole('checkbox', { name: /Dictation/ });
  expect(blind).toBeChecked();
  expect(blind).toHaveAccessibleDescription(/Listen once to the whole passage/);
  expect(dictation).toHaveAccessibleDescription(/Type every word you hear/);
  expect(screen.getByText('Your plan: 4 steps')).toBeInTheDocument();

  fireEvent.click(dictation);
  expect(screen.getByText('Your plan: 5 steps')).toBeInTheDocument();
  const preview = screen.getByText('Your plan: 5 steps').parentElement!;
  expect(
    within(preview)
      .getAllByRole('listitem')
      .map((li) => li.textContent),
  ).toEqual(['Blind', 'Dictation', 'Transcript', 'Card', 'Shadow']);

  fireEvent.click(startButton());

  expect(await screen.findByRole('heading', { name: 'Session page' })).toBeInTheDocument();
  const post = calls.find((c) => c.method === 'POST')!;
  expect(post.body).toEqual({
    content_id: 'clip-1',
    passage: { start_ms: 0, end_ms: 600_000 },
    entry: 'both',
  });
  expect(post.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
});

test('a part starts as 2:30 from the first speech, drawn on the waveform', async () => {
  mockRoutes(routes(clip(), 12));
  renderPage();

  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));
  expect(screen.getByRole('heading', { name: 'Drag the edges, or type the times' })).toBeVisible();
  // Speech starts at 12 s; the part starts half a second earlier, at a whole second.
  await waitFor(() => expect(field('Start')).toHaveValue('00:11'));
  expect(field('End')).toHaveValue('02:41');
  expect(screen.getByText('long').textContent).toBe('2:30 long');
  expect(screen.getByTestId('waveform-bars')).toBeInTheDocument();
  expect(slider('Passage start')).toHaveAttribute('aria-valuetext', '11 seconds');
  expect(slider('Passage end')).toHaveAttribute('aria-valuetext', '2 minutes 41 seconds');
});

test('the handles are sliders the keyboard fully operates, and the fields follow', async () => {
  const { calls } = mockRoutes({
    ...routes(clip()),
    'POST /sessions': () => jsonResponse(201, sessionFixture({ id: 'new-1' })),
  });
  renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));
  await screen.findByTestId('waveform-bars');

  const start = slider('Passage start');
  const end = slider('Passage end');
  expect(start).toHaveAttribute('tabindex', '0');
  expect(start).toHaveAttribute('aria-valuenow', '0');
  expect(start).toHaveAttribute('aria-valuemin', '0');
  expect(start).toHaveAttribute('aria-valuemax', '120');
  expect(end).toHaveAttribute('aria-valuemin', '30');
  expect(end).toHaveAttribute('aria-valuemax', '600');

  fireEvent.keyDown(start, { key: 'ArrowRight' });
  expect(start).toHaveAttribute('aria-valuenow', '1');
  fireEvent.keyDown(start, { key: 'ArrowRight', shiftKey: true });
  expect(start).toHaveAttribute('aria-valuenow', '5');
  fireEvent.keyDown(start, { key: 'PageUp' });
  expect(start).toHaveAttribute('aria-valuenow', '10');
  fireEvent.keyDown(start, { key: 'ArrowLeft' });
  expect(start).toHaveAttribute('aria-valuenow', '9');
  expect(field('Start')).toHaveValue('00:09');

  // End stops 30 s after the start; Home and End jump to the limits.
  fireEvent.keyDown(start, { key: 'End' });
  expect(start).toHaveAttribute('aria-valuenow', '120');
  expect(start).toHaveAttribute('aria-valuetext', '2 minutes');
  fireEvent.keyDown(end, { key: 'Home' });
  expect(end).toHaveAttribute('aria-valuenow', '150');
  fireEvent.keyDown(end, { key: 'End' });
  expect(end).toHaveAttribute('aria-valuenow', '600');
  expect(field('End')).toHaveValue('10:00');
  fireEvent.keyDown(end, { key: 'ArrowDown', shiftKey: true });
  expect(field('End')).toHaveValue('09:55');
  expect(screen.getByText('long').textContent).toBe('7:55 long');

  // The length is announced once the learner stops moving a handle.
  await waitFor(() =>
    expect(screen.getByRole('status')).toHaveTextContent('7 minutes 55 seconds selected'),
  );

  fireEvent.click(startButton());
  await screen.findByRole('heading', { name: 'Session page' });
  expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({
    passage: { start_ms: 120_000, end_ms: 595_000 },
  });
});

test('typed times move the handles, and are adjusted with a message when out of range', async () => {
  const { calls } = mockRoutes({
    ...routes(clip()),
    'POST /sessions': () => jsonResponse(201, sessionFixture({ id: 'new-1' })),
  });
  renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));

  fireEvent.change(field('Start'), { target: { value: '02:10' } });
  fireEvent.blur(field('Start'));
  expect(slider('Passage start')).toHaveAttribute('aria-valuenow', '130');
  // The old end (2:30) was too close, so it moved along.
  expect(field('End')).toHaveValue('02:40');
  expect(field('Start')).toHaveAccessibleDescription(
    'We moved the end to 02:40 so the part is at least 30 seconds.',
  );

  fireEvent.change(field('End'), { target: { value: '02:25' } });
  fireEvent.blur(field('End'));
  expect(field('End')).toHaveValue('02:40');
  expect(field('End')).not.toHaveAttribute('aria-invalid');
  expect(field('End')).toHaveAccessibleDescription(
    'This part is 15 seconds. A part needs at least 30 seconds, so we set the end to 02:40.',
  );

  fireEvent.change(field('End'), { target: { value: '11:00' } });
  fireEvent.blur(field('End'));
  expect(field('End')).toHaveValue('10:00');
  expect(field('End')).toHaveAccessibleDescription(
    '11:00 is after the end of the clip, so we set the end to 10:00.',
  );

  // A typed time that would be adjusted stops the submit, so the learner sees why.
  fireEvent.change(field('End'), { target: { value: '2:20' } });
  fireEvent.click(startButton());
  expect(field('End')).toHaveValue('02:40');
  expect(field('End')).toHaveFocus();
  expect(calls.some((c) => c.method === 'POST')).toBe(false);

  // One that fits is applied and sent.
  fireEvent.change(field('End'), { target: { value: '4:40' } });
  fireEvent.click(startButton());
  await screen.findByRole('heading', { name: 'Session page' });
  expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({
    passage: { start_ms: 130_000, end_ms: 280_000 },
    entry: 'blind',
  });
});

test('a time that is not a time is refused, and the plan does not start', async () => {
  const { calls } = mockRoutes(routes(clip()));
  renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));

  fireEvent.change(field('Start'), { target: { value: 'two' } });
  fireEvent.click(startButton());
  expect(field('Start')).toHaveAttribute('aria-invalid', 'true');
  expect(field('Start')).toHaveAccessibleDescription(
    'Type the start as minutes and seconds, for example 02:10.',
  );
  expect(field('Start')).toHaveFocus();
  expect(calls.some((c) => c.method === 'POST')).toBe(false);

  fireEvent.change(field('Start'), { target: { value: '1:00' } });
  expect(field('Start')).not.toHaveAttribute('aria-invalid');
});

test('a clip over 15 minutes cannot be used whole; 2:30 from the first speech is suggested', async () => {
  mockRoutes(routes(clip({ duration_ms: 2_285_000 }), 40));
  renderPage();

  const whole = await screen.findByRole('radio', { name: /Whole clip · 38:05/ });
  expect(whole).toHaveAttribute('aria-disabled', 'true');
  expect(whole).toHaveAccessibleDescription(
    'Too long to use whole. Choose a part of 15 minutes or less.',
  );
  fireEvent.click(whole);
  expect(whole).not.toBeChecked();
  expect(screen.getByRole('radio', { name: /A part of it/ })).toBeChecked();
  await waitFor(() => expect(field('Start')).toHaveValue('00:39'));
  expect(field('End')).toHaveValue('03:09');

  fireEvent.change(field('Start'), { target: { value: '05:00' } });
  fireEvent.blur(field('Start'));
  fireEvent.change(field('End'), { target: { value: '23:20' } });
  fireEvent.blur(field('End'));
  expect(field('End')).toHaveValue('20:00');
  expect(field('End')).toHaveAccessibleDescription(
    'Start 05:00 to end 23:20 makes 18:20. A part can be 15 minutes at most, so we set the end to 20:00.',
  );
  expect(slider('Passage end')).toHaveAttribute('aria-valuemax', '1200');
});

test('a clip under 30 seconds is too short to practise', async () => {
  mockRoutes(routes(clip({ duration_ms: 25_000 })));
  renderPage();

  expect(
    await screen.findByText(
      'This clip is 00:25 long. A plan needs at least 30 seconds, so add a longer clip.',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start plan' })).not.toBeInTheDocument();
});

test('"Hear start" and "Hear end" play 1.5 s either side of the cut, then stop', async () => {
  mockRoutes(routes(clip()));
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const { container } = renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));
  fireEvent.change(field('Start'), { target: { value: '02:10' } });
  fireEvent.blur(field('Start'));

  const audio = container.querySelector('audio')!;
  expect(audio).toHaveAttribute('src', '/api/v1/media/m-1');
  expect(audio).toHaveAttribute('preload', 'none');

  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: 'Hear start' }));
  expect(audio.currentTime).toBe(128.5);
  expect(play).toHaveBeenCalledTimes(1);
  await act(async () => {});
  pause.mockClear();
  act(() => vi.advanceTimersByTime(2900));
  expect(pause).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(200));
  expect(pause).toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Hear end' }));
  expect(audio.currentTime).toBe(158.5);
  await act(async () => {});
  act(() => vi.advanceTimersByTime(3000));
  expect(pause).toHaveBeenCalledTimes(2);
});

test('when playback fails, the learner is told', async () => {
  mockRoutes(routes(clip()));
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new Error('NotAllowedError'));
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));

  fireEvent.click(screen.getByRole('button', { name: 'Hear end' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The clip could not be played.');
});

test('without the peaks, the part can still be chosen', async () => {
  mockRoutes({
    'GET /contents/clip-1': jsonResponse(200, clip()),
    'GET /media/m-1/peaks': problem(409, 'media_not_ready', 'Not ready.'),
  });
  renderPage();
  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));

  expect(
    await screen.findByText(
      'The waveform could not be loaded. You can still move the edges or type the times.',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByTestId('waveform-bars')).not.toBeInTheDocument();
  fireEvent.keyDown(slider('Passage end'), { key: 'ArrowRight' });
  expect(field('End')).toHaveValue('02:31');
});

test('with nothing ticked, the plan does not start and says why', async () => {
  const { calls } = mockRoutes(routes(clip()));
  renderPage();

  fireEvent.click(await screen.findByRole('checkbox', { name: /Blind/ }));
  expect(screen.getByText('Your plan: tick Blind, Dictation or both.')).toBeInTheDocument();
  fireEvent.click(startButton());

  expect(screen.getByText('Tick Blind, Dictation or both.')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: /Blind/ })).toHaveFocus();
  expect(calls.some((c) => c.method === 'POST')).toBe(false);
});

test('a clip that is still being prepared cannot start a plan yet', async () => {
  mockRoutes({
    'GET /contents/clip-1': jsonResponse(
      200,
      clip({ status: 'pending', duration_ms: null, media_url: null, peaks_url: null }),
    ),
  });
  renderPage();

  expect(
    await screen.findByText(
      'This clip is still being prepared. You can start a plan as soon as it is ready.',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start plan' })).not.toBeInTheDocument();
});

test('a refusal is shown, and a retry of the same plan reuses its Idempotency-Key', async () => {
  let posts = 0;
  const { calls } = mockRoutes({
    ...routes(clip()),
    'POST /sessions': () => {
      posts += 1;
      return posts === 1
        ? problem(503, 'service_unavailable', 'The service is busy.')
        : jsonResponse(201, sessionFixture({ id: 'new-1' }));
    },
  });
  renderPage();

  fireEvent.click(await screen.findByRole('button', { name: 'Start plan' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The service is busy.');
  fireEvent.click(startButton());

  await screen.findByRole('heading', { name: 'Session page' });
  const keys = calls.filter((c) => c.method === 'POST').map((c) => c.headers['Idempotency-Key']);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test('a clip that is not in the library is reported', async () => {
  mockRoutes({
    'GET /contents/clip-1': problem(
      404,
      'content_not_found',
      'This clip is not in your library. Go back to the library.',
    ),
  });
  renderPage();

  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent('This clip is not in your library.'),
  );
});
