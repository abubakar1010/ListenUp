import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { ShadowRounds } from './ShadowRounds';

it('discloses round 1 text only, advances explicitly, and never claims recording completion', async () => {
  let number = 1;
  const segment = {
    session_id: 's',
    start_ms: 0,
    end_ms: 60000,
    chosen_by: 'system',
    mark_count: 0,
    locked_at: 'now',
  };
  const { calls } = mockRoutes({
    'GET /sessions/s/shadow/rounds': () =>
      jsonResponse(200, {
        segment,
        current: {
          round: number,
          transcript_shown: number === 1,
          playback_status: 'ended',
          recorded_at: null,
        },
        rounds: [],
        ...(number === 1 ? { text: 'Secret segment words.' } : {}),
      }),
    'POST /sessions/s/shadow/rounds/2/start': () => {
      number = 2;
      return new Response(null, { status: 204 });
    },
    'POST /sessions/s/shadow/rounds/3/start': () => {
      number = 3;
      return new Response(null, { status: 204 });
    },
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
  });
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await screen.findByText('Secret segment words.');
  fireEvent.click(screen.getByRole('button', { name: 'Start round 2' }));
  await screen.findByText('Round 2 of 3');
  expect(screen.getByRole('heading', { name: 'Round 2 of 3' })).toHaveFocus();
  expect(screen.queryByText('Secret segment words.')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Start round 3' }));
  await screen.findByText('Round 3 of 3');
  expect(screen.queryByRole('button', { name: 'Start round 4' })).not.toBeInTheDocument();
  expect(screen.getByText(/No recording has been saved/)).toBeInTheDocument();
  await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2));
  expect(calls.every((c) => !c.path.includes('/complete'))).toBe(true);
});

it('retries a refused start using the same action and idempotency key', async () => {
  let attempts = 0;
  const segment = {
    session_id: 's',
    start_ms: 0,
    end_ms: 60000,
    chosen_by: 'system',
    mark_count: 0,
    locked_at: null,
  };
  const { calls } = mockRoutes({
    'GET /sessions/s/shadow/rounds': jsonResponse(200, { segment, current: null, rounds: [] }),
    'POST /sessions/s/shadow/rounds/1/start': () => {
      attempts++;
      return attempts === 1
        ? jsonResponse(503, { code: 'unavailable', detail: 'Try starting again.' })
        : new Response(null, { status: 204 });
    },
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
  });
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Start round 1' }));
  await screen.findByText('Try starting again.');
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(attempts).toBe(2));
  const writes = calls.filter((c) => c.method === 'POST');
  expect(writes.map((c) => c.path)).toEqual([
    '/sessions/s/shadow/rounds/1/start',
    '/sessions/s/shadow/rounds/1/start',
  ]);
  expect(writes[0].headers['Idempotency-Key']).toBe(writes[1].headers['Idempotency-Key']);
});

it('reports a bounded playback end to the API and updates numbered round status', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  let ended = false;
  const segment = {
    session_id: 's',
    start_ms: 10000,
    end_ms: 70000,
    chosen_by: 'system',
    mark_count: 0,
    locked_at: 'now',
  };
  const { calls } = mockRoutes({
    'GET /sessions/s/shadow/rounds': () => {
      const current = {
        round: 1,
        transcript_shown: true,
        playback_status: ended ? 'ended' : 'ready',
        recorded_at: null,
      };
      return jsonResponse(200, { segment, current, rounds: [current], text: 'First-round words.' });
    },
    'POST /sessions/s/shadow/rounds/1/playback-ended': () => {
      ended = true;
      return new Response(null, { status: 204 });
    },
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
  });
  const view = renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await screen.findByRole('button', { name: 'Play round 1' });
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  vi.useFakeTimers();
  try {
    fireEvent.click(screen.getByRole('button', { name: 'Play round 1' }));
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    audio.currentTime = 70.5;
    fireEvent.timeUpdate(audio);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
  } finally {
    vi.useRealTimers();
  }
  await screen.findByRole('button', { name: 'Start round 2' });
  expect(screen.getByRole('list', { name: 'Round status' })).toHaveTextContent(
    'Round 1: playback ended',
  );
  expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
    '/sessions/s/shadow/rounds/1/playback-ended',
  ]);
  view.unmount();
  vi.restoreAllMocks();
});
