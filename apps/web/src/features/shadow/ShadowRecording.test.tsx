import { useEffect } from 'react';
vi.mock('./ShadowReadiness', () => ({
  ShadowReadiness: ({ onReady }: { onReady: (ready: boolean) => void }) => {
    useEffect(() => onReady(true), [onReady]);
    return null;
  },
}));
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { ShadowRounds } from './ShadowRounds';

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static supported = new Set(['audio/webm;codecs=opus', 'audio/mp4']);
  static isTypeSupported(type: string) {
    return FakeRecorder.supported.has(type);
  }
  state = 'inactive';
  mimeType: string;
  private listeners: Record<string, ((event: unknown) => void)[]> = {};
  constructor(
    readonly stream: MediaStream,
    options: { mimeType: string },
  ) {
    this.mimeType = options.mimeType;
    FakeRecorder.instances.push(this);
  }
  addEventListener(name: string, listener: (event: unknown) => void) {
    (this.listeners[name] ??= []).push(listener);
  }
  removeEventListener() {}
  private emit(name: string, event: unknown = {}) {
    this.listeners[name]?.forEach((listener) => listener(event));
  }
  start() {
    this.state = 'recording';
  }
  stop() {
    this.state = 'inactive';
    this.emit('dataavailable', { data: new Blob(['a'.repeat(2000)], { type: this.mimeType }) });
    this.emit('stop');
  }
}

const track = { stop: vi.fn() };
const segment = {
  session_id: 's',
  start_ms: 10000,
  end_ms: 70000,
  chosen_by: 'system',
  mark_count: 0,
  locked_at: 'now',
};

beforeEach(() => {
  FakeRecorder.instances = [];
  FakeRecorder.supported = new Set(['audio/webm;codecs=opus', 'audio/mp4']);
  track.stop.mockClear();
  vi.stubGlobal('MediaRecorder', FakeRecorder);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [track],
        getAudioTracks: () => [track],
      })),
    },
  });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stateOf(phase: 'ready' | 'ended' | 'saved') {
  const current = {
    id: 'r1',
    round: 1,
    transcript_shown: true,
    playback_status: phase === 'ready' ? 'ready' : 'ended',
    recorded_at: phase === 'saved' ? '2026-10-27T10:00:00Z' : null,
    recording_available: phase === 'saved',
    feedback: phase === 'saved' ? 'unavailable' : null,
  };
  return { segment, current, rounds: [current], text: 'First-round words.' };
}

async function playRound() {
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
}

function routes(extra: Parameters<typeof mockRoutes>[0] = {}) {
  let phase: 'ready' | 'ended' | 'saved' = 'ready';
  return mockRoutes({
    'GET /sessions/s/shadow/rounds': () => jsonResponse(200, stateOf(phase)),
    'POST /sessions/s/shadow/rounds/1/playback-ended': () => {
      phase = 'ended';
      return new Response(null, { status: 204 });
    },
    'POST /sessions/s/shadow/rounds/1/recording': jsonResponse(200, {
      round_id: 'r1',
      upload: {
        url: 'https://storage.test/put',
        method: 'PUT',
        headers: { 'Content-Type': 'audio/webm' },
        expires_at: '2026-10-27T10:05:00Z',
      },
    }),
    'PUT https://storage.test/put': new Response(null, { status: 200 }),
    'POST /shadow/rounds/r1/complete': () => {
      phase = 'saved';
      return new Response(null, { status: 204 });
    },
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    ...extra,
  });
}

it('records from the count-in to the end, uploads it and replays it next to the original', async () => {
  const { calls } = routes();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await playRound();
  await screen.findByText(/Recording saved/);
  expect(FakeRecorder.instances).toHaveLength(1);
  expect(FakeRecorder.instances[0].mimeType).toBe('audio/webm;codecs=opus');
  expect(calls.map((c) => `${c.method} ${c.path}`).filter((c) => !c.startsWith('GET'))).toEqual([
    'POST /sessions/s/shadow/rounds/1/playback-ended',
    'POST /sessions/s/shadow/rounds/1/recording',
    'PUT https://storage.test/put',
    'POST /shadow/rounds/r1/complete',
  ]);
  expect(calls.find((c) => c.path.endsWith('/recording'))!.body).toEqual({
    mime: 'audio/webm',
    size_bytes: 2000,
  });
  expect(track.stop).toHaveBeenCalled();
  expect(screen.getByText(/Feedback unavailable/)).toBeInTheDocument();
  const mine = screen.getByLabelText('Your recording of round 1');
  expect(mine).toHaveAttribute('src', '/api/v1/shadow/rounds/r1/recording');
  const original = screen.getByLabelText('Original, round 1 segment');
  expect(original.getAttribute('src')).toBe('/audio#t=10,70');
  expect(screen.getByRole('list', { name: 'Round status' })).toHaveTextContent('Round 1: recorded');
});

it('records AAC in MP4 where Opus in WebM is not supported', async () => {
  FakeRecorder.supported = new Set(['audio/mp4']);
  const { calls } = routes();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await playRound();
  await screen.findByText(/Recording saved/);
  expect(FakeRecorder.instances[0].mimeType).toBe('audio/mp4');
  expect(calls.find((c) => c.path.endsWith('/recording'))!.body).toMatchObject({
    mime: 'audio/mp4',
  });
});

it('retries a failed upload without recording again', async () => {
  let puts = 0;
  const { calls } = routes({
    'PUT https://storage.test/put': () => {
      puts++;
      return puts === 1 ? new Response(null, { status: 503 }) : new Response(null, { status: 200 });
    },
  });
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await playRound();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry upload' }));
  await screen.findByText(/Recording saved/);
  expect(puts).toBe(2);
  expect(FakeRecorder.instances).toHaveLength(1);
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
  expect(calls.filter((c) => c.path.endsWith('/rounds/1/recording'))).toHaveLength(2);
  expect(screen.queryByRole('button', { name: 'Retry upload' })).not.toBeInTheDocument();
});

it('says so and lets the plan go on when the browser cannot record', async () => {
  vi.stubGlobal('MediaRecorder', undefined);
  const { calls } = routes();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await playRound();
  await screen.findByText(/cannot record/);
  await waitFor(() =>
    expect(calls.some((c) => c.path === '/sessions/s/shadow/rounds/1/playback-ended')).toBe(true),
  );
  expect(calls.some((c) => c.path.includes('/recording'))).toBe(false);
});

it('discards the recording when the round is stopped', async () => {
  const { calls } = routes();
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await screen.findByRole('button', { name: 'Play round 1' });
  fireEvent.loadedMetadata(document.querySelector('audio')!);
  fireEvent.click(screen.getByRole('button', { name: 'Play round 1' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Stop round 1' }));
  await waitFor(() => expect(track.stop).toHaveBeenCalled());
  expect(calls.some((c) => c.path.includes('/recording'))).toBe(false);
});
