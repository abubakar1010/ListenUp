import { useEffect } from 'react';
vi.mock('./ShadowReadiness', () => ({
  ShadowReadiness: ({ onReady }: { onReady: (ready: boolean) => void }) => {
    useEffect(() => onReady(true), [onReady]);
    return null;
  },
}));
import { MemoryRouter } from 'react-router';
import { focusManager, QueryClientProvider } from '@tanstack/react-query';
import { createQueryClient } from '../../app/queryClient';
import { roundsKey } from './api';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { ShadowRounds } from './ShadowRounds';

it('discloses round 1 text only, advances explicitly, and never completes a round without an upload', async () => {
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
  expect(screen.getByText(/Playback alone does not complete Shadow/)).toBeInTheDocument();
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

it.each(['before effects', 'after effects'])(
  'reports a bounded playback end to the API and updates numbered round status (%s metadata)',
  async (metadataTiming) => {
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
        return jsonResponse(200, {
          segment,
          current,
          rounds: [current],
          text: 'First-round words.',
        });
      },
      'POST /sessions/s/shadow/rounds/1/playback-ended': () => {
        ended = true;
        return new Response(null, { status: 204 });
      },
      'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    });
    // JSDOM does not load media: model both the state change and its notification.
    // A browser retains HAVE_METADATA even if the event precedes effect attachment.
    const metadataLoaded = (element: HTMLMediaElement) => {
      vi.spyOn(element, 'readyState', 'get').mockReturnValue(HTMLMediaElement.HAVE_METADATA);
      fireEvent.loadedMetadata(element);
    };
    const observer = new MutationObserver(() => {
      const mounted = document.querySelector('audio');
      if (mounted) {
        observer.disconnect();
        metadataLoaded(mounted);
      }
    });
    let view: ReturnType<typeof renderWithProviders> | undefined;
    try {
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
      vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
      if (metadataTiming === 'before effects') {
        observer.observe(document.body, { childList: true, subtree: true });
      }
      view = renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
      await screen.findByRole('button', { name: 'Play round 1' });
      const audio = document.querySelector('audio')!;
      if (metadataTiming === 'after effects') metadataLoaded(audio);
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Play round 1' })).toBeEnabled(),
      );
      vi.useFakeTimers();
      try {
        fireEvent.click(screen.getByRole('button', { name: 'Play round 1' }));
        // Three-second count-in (ADR 0063): no playback until it has fully elapsed.
        expect(screen.getByRole('status')).toHaveTextContent('Round 1 starts in 3');
        await act(async () => {
          vi.advanceTimersByTime(2999);
        });
        expect(audio.play).not.toHaveBeenCalled();
        await act(async () => {
          vi.advanceTimersByTime(1);
        });
        expect(audio.play).toHaveBeenCalledTimes(1);
        expect(screen.getByRole('status')).toHaveTextContent('playing at original speed');
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
    } finally {
      observer.disconnect();
      view?.unmount();
      vi.useRealTimers();
      vi.restoreAllMocks();
    }
  },
);

it.each(['before settlement', 'after settlement'])(
  'keeps transcript hidden when a focus refetch resolves %s and advancement refresh fails',
  async (ordering) => {
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    let resolveStart!: (response: Response) => void;
    const start = new Promise<Response>((resolve) => {
      resolveStart = resolve;
    });
    let resolveRead!: (response: Response) => void;
    const read = new Promise<Response>((resolve) => {
      resolveRead = resolve;
    });
    const segment = {
      session_id: 's',
      start_ms: 0,
      end_ms: 60000,
      chosen_by: 'system',
      mark_count: 0,
      locked_at: 'now',
    };
    const current = {
      round: 1,
      transcript_shown: true,
      playback_status: 'ended',
      recorded_at: null,
    };
    const firstRound = { segment, current, rounds: [current], text: 'Secret round-one words.' };
    let reads = 0;
    const { calls } = mockRoutes({
      'GET /sessions/s/shadow/rounds': () => {
        reads++;
        if (reads === 1) return jsonResponse(200, firstRound);
        if (reads === 2) return read;
        return jsonResponse(503, { code: 'unavailable', detail: 'Round refresh failed.' });
      },
      'POST /sessions/s/shadow/rounds/2/start': () => start,
      'GET /sessions/s/shadow/segment': jsonResponse(200, segment),
      'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    });
    const view = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ShadowRounds sessionId="s" contentId="c" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    try {
      await screen.findByText(firstRound.text);
      fireEvent.click(screen.getByRole('button', { name: 'Start round 2' }));
      await waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1));
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });
      await waitFor(() => expect(reads).toBe(2));
      if (ordering === 'before settlement') {
        await act(async () => {
          resolveRead(jsonResponse(200, firstRound));
        });
        await waitFor(() =>
          expect(client.getQueryData(roundsKey('s'))).toMatchObject({ text: firstRound.text }),
        );
        expect(screen.queryByText(firstRound.text)).not.toBeInTheDocument();
      }
      await act(async () => {
        resolveStart(new Response(null, { status: 204 }));
      });
      await screen.findByText('Round refresh failed.');
      if (ordering === 'after settlement') {
        await act(async () => {
          resolveRead(jsonResponse(200, firstRound));
        });
      }
      await waitFor(() => expect(client.isMutating()).toBe(0));
      expect(screen.queryByText(firstRound.text)).not.toBeInTheDocument();
      expect(client.getQueryData(roundsKey('s'))).not.toHaveProperty('text', firstRound.text);
    } finally {
      view.unmount();
      client.clear();
      focusManager.setFocused(undefined);
    }
  },
);

it('hides cached transcript after a failed refresh and restores it only after a successful retry', async () => {
  let reads = 0;
  const current = { round: 1, transcript_shown: true, playback_status: 'ended', recorded_at: null };
  mockRoutes({
    'GET /sessions/s/shadow/rounds': () => {
      reads++;
      return reads === 2
        ? jsonResponse(503, { code: 'unavailable', detail: 'Round refresh failed.' })
        : jsonResponse(200, {
            segment: {
              session_id: 's',
              start_ms: 0,
              end_ms: 60000,
              chosen_by: 'system',
              mark_count: 0,
              locked_at: 'now',
            },
            current,
            rounds: [current],
            text: 'Round-one transcript.',
          });
    },
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
  });
  const view = renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  try {
    await screen.findByText('Round-one transcript.');
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await screen.findByText('Round refresh failed.');
    expect(screen.queryByText('Round-one transcript.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText('Round-one transcript.');
    expect(reads).toBe(3);
  } finally {
    view.unmount();
    focusManager.setFocused(undefined);
  }
});

it('deletes a recording from the round replay; the round still counts as recorded (FR-SH-17)', async () => {
  let deleted = false;
  const recorded = (n: number, available: boolean) => ({
    id: `r${n}`,
    round: n,
    transcript_shown: n === 1,
    playback_status: 'ended',
    recorded_at: '2026-10-27T10:00:00Z',
    recording_available: available,
    feedback: 'unavailable',
  });
  const { calls } = mockRoutes({
    'GET /sessions/s/shadow/rounds': () =>
      jsonResponse(200, {
        segment: { start_ms: 0, end_ms: 60000 },
        current: recorded(1, !deleted),
        rounds: [recorded(1, !deleted)],
      }),
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    'DELETE /shadow/rounds/r1/recording': () => {
      deleted = true;
      return new Response(null, { status: 204 });
    },
  });
  const onStatus = vi.fn();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" onStatus={onStatus} />);
  const status = await screen.findByRole('list', { name: 'Round status' });
  expect(status).toHaveTextContent('Round 1: recorded');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete recording of round 1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete recording' }));
  await waitFor(() => expect(onStatus).toHaveBeenCalledWith('Recording of round 1 deleted.'));
  await waitFor(() =>
    expect(screen.queryByRole('region', { name: 'Round 1 replay' })).not.toBeInTheDocument(),
  );
  expect(status).toHaveTextContent('Round 1: recorded, recording deleted');
  expect(screen.getByRole('button', { name: 'Start round 2' })).toBeInTheDocument();
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
});
