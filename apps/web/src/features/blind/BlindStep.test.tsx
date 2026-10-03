import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes } from '../session/testApi';
import { attemptFixture, blindStepFixture } from './fixtures';

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

const SESSION = 'GET /sessions/session-1';
const BLIND = 'GET /sessions/session-1/blind';

function renderBlind() {
  return renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: '/sessions/session-1' },
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
  expect(screen.queryByRole('button', { name: 'Start listening' })).toBeNull();
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
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
