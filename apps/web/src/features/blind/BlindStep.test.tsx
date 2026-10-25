import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Route, RouterProvider, Routes } from 'react-router';
import { createQueryClient } from '../../app/queryClient';

import { jsonResponse, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes } from '../session/testApi';
import { attemptFixture, blindStepFixture } from './fixtures';

test('Continue refreshes a fresh completed-listen cache before showing Transcript feedback', async () => {
  let submitted = false;
  const gist = 'This is the idea. Here is another detail. I heard this too.';
  mockRoutes({
    [SESSION]: () => jsonResponse(200, sessionFixture({ entry: 'blind', done: submitted ? 1 : 0 })),
    [BLIND]: () =>
      jsonResponse(
        200,
        blindStepFixture(
          attemptFixture({
            listen_complete: true,
            status: submitted ? 'submitted' : 'active',
            gist_text: submitted ? gist : null,
          }),
        ),
      ),
    'POST /blind/attempts/attempt-1/gist': () => {
      submitted = true;
      return jsonResponse(201, {
        attempt: attemptFixture({ status: 'submitted', gist_text: gist }),
        open_step: 'transcript',
        session_version: 1,
      });
    },
    'GET /gists/attempt-1/grade': jsonResponse(200, {
      status: 'ready',
      overall: 80,
      gist,
      feedback: 'Full feedback beside Transcript.',
    }),
    'GET /sessions/session-1/transcript': jsonResponse(200, {
      session_id: 'session-1',
      passage: sessionFixture().passage,
      media_url: '/api/v1/media/test',
      lines: [],
    }),
    'GET /sessions/session-1/marks': jsonResponse(200, { marks: [] }),
  });
  // Preserve the production 30-second freshness window; the shared test helper resets it.
  const queryClient = createQueryClient();
  const router = createMemoryRouter([{ path: '/sessions/:sessionId', element: <SessionPage /> }], {
    initialEntries: ['/sessions/session-1'],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  fireEvent.change(await screen.findByRole('textbox', { name: 'Your gist' }), {
    target: { value: gist },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Continue to Transcript' }));
  await waitFor(() => {
    const aside = screen.getByRole('complementary', { name: 'Side panel' });
    expect(within(aside).getByText(gist)).toBeInTheDocument();
    expect(within(aside).getByText('Full feedback beside Transcript.')).toBeInTheDocument();
  });
});

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

const SESSION = 'GET /sessions/session-1';
const BLIND = 'GET /sessions/session-1/blind';

function renderBlind(historyEntries = ['/sessions/session-1']) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/library"
        element={
          <main>
            <h1>Library</h1>
          </main>
        }
      />
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { historyEntries },
  );
}

test('before the start: the rules, Start and volume, and no other playback control', async () => {
  mockRoutes({ [SESSION]: jsonResponse(200, sessionFixture({ entry: 'both' })) });
  const { container } = renderBlind();

  expect(await screen.findByRole('heading', { name: 'Before you start' })).toBeInTheDocument();
  const player = screen.getByRole('group', { name: 'Blind player' });
  expect(
    within(player)
      .getAllByRole('button')
      .map((b) => b.textContent),
  ).toEqual(['Start listening']);
  expect(within(player).getByRole('slider', { name: 'Volume' })).toBeInTheDocument();
  expect(within(player).getByText('Pause, seek and speed are off')).toBeInTheDocument();
  expect(
    within(player).getByRole('progressbar', { name: 'Playback progress' }),
  ).not.toHaveAttribute('tabindex');
  expect(screen.queryByRole('button', { name: /pause|seek|rewind|speed|replay/i })).toBeNull();
  const audio = container.ownerDocument.querySelector('audio')!;
  expect(audio).not.toHaveAttribute('controls');
  expect(audio).toHaveAttribute('tabindex', '-1');
  expect(screen.getByText('No pausing. Listen once, all the way through.')).toBeInTheDocument();
  expect(screen.getByText('2:30')).toBeInTheDocument();
});

test('Start begins one attempt, loads the passage and hides the way out', async () => {
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'both' })),
    'POST /sessions/session-1/blind/attempts': jsonResponse(201, {
      attempt: attemptFixture(),
      media_url: '/api/v1/blind/attempts/attempt-1/media/token',
      heartbeat_interval_ms: 5_000,
      resume_delay_ms: 3_000,
    }),
  });
  const { container } = renderBlind();

  fireEvent.click(await screen.findByRole('button', { name: 'Start listening' }));

  expect(await screen.findByText('Starting')).toBeInTheDocument();
  const audio = container.ownerDocument.querySelector('audio')!;
  expect(audio.getAttribute('src')).toBe('/api/v1/blind/attempts/attempt-1/media/token');
  expect(audio.preload).toBe('auto');
  expect(screen.queryByRole('link', { name: 'Library' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Change entry' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Plan' })).toBeNull(); // UX-19
  expect(screen.queryByRole('button', { name: 'Start listening' })).toBeNull();
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
});

test('Browser Back asks first; Stay keeps playback running and Leave voids before navigating', async () => {
  let resolveVoid: (response: Response) => void = () => {};
  const voidResponse = new Promise<Response>((resolve) => {
    resolveVoid = resolve;
  });
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    'POST /sessions/session-1/blind/attempts': jsonResponse(201, {
      attempt: attemptFixture(),
      media_url: '/api/v1/blind/attempts/attempt-1/media/token',
      heartbeat_interval_ms: 5_000,
      resume_delay_ms: 3_000,
    }),
    'POST /blind/attempts/attempt-1/void': () => voidResponse,
  });
  const { router, container } = renderBlind(['/library', '/sessions/session-1']);
  const start = await screen.findByRole('button', { name: 'Start listening' });
  const audio = container.querySelector('audio')!;
  let paused = true;
  Object.defineProperty(audio, 'paused', { configurable: true, get: () => paused });
  vi.spyOn(audio, 'play').mockImplementation(async () => {
    paused = false;
  });
  const pause = vi.spyOn(audio, 'pause').mockImplementation(() => {
    paused = true;
  });

  fireEvent.click(start);
  await screen.findByText('Starting');
  fireEvent.canPlay(audio);
  await waitFor(() => expect(paused).toBe(false));
  fireEvent.playing(audio);
  await screen.findByText('Listening', { exact: true });

  await act(async () => router.navigate(-1));
  const dialog = await screen.findByRole('dialog', { name: 'Leave Blind?' });
  expect(dialog).toHaveTextContent('Playback keeps going while you decide.');
  expect(paused).toBe(false);
  expect(pause).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole('button', { name: 'Stay' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(router.state.location.pathname).toBe('/sessions/session-1');
  expect(paused).toBe(false);
  expect(pause).not.toHaveBeenCalled();

  await act(async () => router.navigate(-1));
  fireEvent.click(await screen.findByRole('button', { name: 'Leave Blind' }));
  await waitFor(() =>
    expect(calls.some((call) => call.path === '/blind/attempts/attempt-1/void')).toBe(true),
  );
  expect(screen.getByRole('dialog', { name: 'Leave Blind?' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/sessions/session-1');
  expect(paused).toBe(false);

  resolveVoid(jsonResponse(200, attemptFixture({ status: 'voided', void_reason: 'left_page' })));
  await screen.findByRole('heading', { name: 'Library' });
  expect(calls.find((call) => call.path === '/blind/attempts/attempt-1/void')?.body).toEqual({
    reason: 'left_page',
  });
  expect(paused).toBe(true);
});

test('a failed leave void stays on the page and can be retried', async () => {
  let voidCalls = 0;
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    'POST /sessions/session-1/blind/attempts': jsonResponse(201, {
      attempt: attemptFixture(),
      media_url: '/api/v1/blind/attempts/attempt-1/media/token',
      heartbeat_interval_ms: 5_000,
      resume_delay_ms: 3_000,
    }),
    'POST /blind/attempts/attempt-1/void': () => {
      voidCalls += 1;
      return voidCalls === 1
        ? jsonResponse(503, {
            type: '/problems/unavailable',
            title: 'Service Unavailable',
            status: 503,
            code: 'unavailable',
            detail: 'Try again.',
          })
        : jsonResponse(200, attemptFixture({ status: 'voided', void_reason: 'left_page' }));
    },
  });
  const { router, container } = renderBlind(['/library', '/sessions/session-1']);
  fireEvent.click(await screen.findByRole('button', { name: 'Start listening' }));
  await screen.findByText('Starting');
  const audio = container.querySelector('audio')!;
  let paused = true;
  Object.defineProperty(audio, 'paused', { configurable: true, get: () => paused });
  vi.spyOn(audio, 'play').mockImplementation(async () => {
    paused = false;
  });
  vi.spyOn(audio, 'pause').mockImplementation(() => {
    paused = true;
  });
  fireEvent.canPlay(audio);
  await waitFor(() => expect(paused).toBe(false));
  fireEvent.playing(audio);
  await screen.findByText('Listening', { exact: true });
  await act(async () => router.navigate(-1));
  fireEvent.click(await screen.findByRole('button', { name: 'Leave Blind' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong on our side');
  expect(screen.getByRole('dialog', { name: 'Leave Blind?' })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/sessions/session-1');
  expect(paused).toBe(false);

  fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Try again' }));
  await screen.findByRole('heading', { name: 'Library' });
  expect(voidCalls).toBe(2);
  expect(calls.filter((call) => call.path.endsWith('/void'))).toHaveLength(2);
});

test('the gist and navigation unlock only after the server acknowledges completion', async () => {
  let acknowledge: (response: Response) => void = () => {};
  const finalBeat = new Promise<Response>((resolve) => (acknowledge = resolve));
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    'POST /sessions/session-1/blind/attempts': jsonResponse(201, {
      attempt: attemptFixture(),
      media_url: '/api/v1/blind/attempts/attempt-1/media/token',
      heartbeat_interval_ms: 5_000,
      resume_delay_ms: 3_000,
    }),
    'POST /blind/attempts/attempt-1/heartbeat': () => finalBeat,
  });
  const { router, container } = renderBlind(['/library', '/sessions/session-1']);
  fireEvent.click(await screen.findByRole('button', { name: 'Start listening' }));
  await screen.findByText('Starting');
  const audio = container.querySelector('audio')!;
  fireEvent.playing(audio);
  audio.currentTime = 280;
  fireEvent.timeUpdate(audio);

  expect(await screen.findByText('Saving your listen. Keep this screen open.')).toHaveAttribute(
    'role',
    'status',
  );
  expect(screen.queryByRole('textbox', { name: 'Your gist' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Library' })).not.toBeInTheDocument();
  await act(async () => router.navigate(-1));
  fireEvent.click(await screen.findByRole('button', { name: 'Stay' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

  acknowledge(
    jsonResponse(200, {
      action: 'continue',
      attempt: attemptFixture({ position_ms: 280_000, listen_complete: true }),
      resume_from_ms: null,
      resume_delay_ms: 3_000,
    }),
  );
  await screen.findByRole('textbox', { name: 'Your gist' });
  await act(async () => router.navigate(-1));
  await screen.findByRole('heading', { name: 'Library' });
  expect(calls.filter((call) => call.path.endsWith('/void'))).toHaveLength(0);
});

test('a server-completed listen can leave the gist form without voiding', async () => {
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    [BLIND]: jsonResponse(
      200,
      blindStepFixture(attemptFixture({ position_ms: 280_000, listen_complete: true })),
    ),
  });
  const { router } = renderBlind(['/library', '/sessions/session-1']);

  expect(await screen.findByRole('textbox', { name: 'Your gist' })).toBeInTheDocument();
  expect(calls.filter((call) => call.path.endsWith('/void'))).toHaveLength(0);
  await act(async () => router.navigate(-1));

  expect(await screen.findByRole('heading', { name: 'Library' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(calls.filter((call) => call.path.endsWith('/void'))).toHaveLength(0);
});

test('an attempt that ended says why and how to go on', async () => {
  mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    [BLIND]: jsonResponse(
      200,
      blindStepFixture(
        attemptFixture({ status: 'voided', void_reason: 'left_page', position_ms: 202_000 }),
      ),
    ),
  });
  renderBlind();

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Your Blind attempt ended');
  // The rule working, not an error: the calm caution style (UX-12, UX-17).
  expect(alert).toHaveAttribute('data-tone', 'caution');
  expect(alert).toHaveTextContent(
    'You left the page at 01:12. Blind needs one full listen, so you start again from 00:00.',
  );
  expect(screen.getByRole('button', { name: 'Start listening' })).toBeInTheDocument();
});

test('a second interruption names when the resume was used', async () => {
  mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    [BLIND]: jsonResponse(
      200,
      blindStepFixture(
        attemptFixture({
          status: 'voided',
          void_reason: 'interrupted',
          position_ms: 255_000,
          resume_count: 1,
          resume_stop_ms: 202_000,
        }),
      ),
    ),
  });
  renderBlind();

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Playback stopped again at 02:05. Blind can carry on once per attempt, and that was used at 01:12.',
  );
});

test('a listen cut short by a reload is ended and explained', async () => {
  const live = attemptFixture({ position_ms: 160_000 });
  const { calls } = mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    [BLIND]: jsonResponse(200, blindStepFixture(live)),
    'POST /blind/attempts/attempt-1/void': jsonResponse(200, {
      ...live,
      status: 'voided',
      void_reason: 'reload',
    }),
  });
  renderBlind();

  expect(await screen.findByRole('alert')).toHaveTextContent('The page reloaded at 00:30.');
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ reason: 'reload' });
});

test('a listen heard to the end shows the gist form, with no replay', async () => {
  mockRoutes({
    [SESSION]: jsonResponse(200, sessionFixture({ entry: 'blind' })),
    [BLIND]: jsonResponse(
      200,
      blindStepFixture(attemptFixture({ position_ms: 280_000, listen_complete: true })),
    ),
  });
  renderBlind();

  expect(await screen.findByRole('heading', { name: 'What was it about?' })).toBeInTheDocument();
  expect(screen.getByText('Listen complete')).toBeInTheDocument();
  expect(screen.getByText('Blind plays once. No replay.')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start listening' })).toBeNull();
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Your gist' })).toHaveFocus());
});

test('submission keeps feedback visible until Continue opens the next step', async () => {
  let submitted = false;
  mockRoutes({
    [SESSION]: () => jsonResponse(200, sessionFixture({ entry: 'both', done: submitted ? 1 : 0 })),
    [BLIND]: jsonResponse(
      200,
      blindStepFixture(attemptFixture({ listen_complete: true, position_ms: 280000 })),
    ),
    'POST /blind/attempts/attempt-1/gist': () => {
      submitted = true;
      return jsonResponse(201, {
        attempt: attemptFixture({ status: 'submitted' }),
        open_step: 'dictation',
        session_version: 1,
      });
    },
    'GET /gists/attempt-1/grade': jsonResponse(200, {
      status: 'ready',
      overall: 80,
      level: 'good',
      dimension_scores: { main_idea: 90 },
      captured_count: 2,
      total_count: 3,
    }),
  });
  renderBlind();
  fireEvent.change(await screen.findByRole('textbox', { name: 'Your gist' }), {
    target: { value: 'This is the idea. Here is another detail. I heard this too.' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));
  expect(await screen.findByText('80 / 100')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Continue to Dictation' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Dictation' }));
  expect(await screen.findByRole('heading', { name: /Dictation:/ })).toBeInTheDocument();
});
