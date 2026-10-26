import { fireEvent, screen, waitFor } from '@testing-library/react';
import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import { mockRoutes } from '../session/testApi';
import { ShadowScreen } from './ShadowScreen';

const session = sessionFixture({ done: 3, passage: { start_ms: 10_000, end_ms: 160_000 } });
const segment = {
  session_id: session.id,
  start_ms: 10_000,
  end_ms: 100_000,
  chosen_by: 'system',
  mark_count: 4,
  locked_at: null as string | null,
};
const path = `/sessions/${session.id}/shadow/segment`;
function setup(value = segment, put?: Response, currentSession = session) {
  const routes = mockRoutes({
    [`GET ${path}`]: jsonResponse(200, value),
    [`PUT ${path}`]:
      put ??
      ((call) => jsonResponse(200, { ...value, ...(call.body as object), chosen_by: 'learner' })),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/audio', peaks_url: null }),
  });
  renderWithProviders(<ShadowScreen session={currentSession} progress={null} />);
  return routes;
}

afterEach(() => vi.restoreAllMocks());

it('keyboard handles enforce 60 to 90 seconds and save absolute times', async () => {
  const { calls } = setup();
  const start = await screen.findByRole('slider', { name: 'Segment start' });
  start.focus();
  fireEvent.keyDown(document.activeElement!, { key: 'End' });
  expect(start).toHaveAttribute('aria-valuenow', '30');
  const end = screen.getByRole('slider', { name: 'Segment end' });
  end.focus();
  fireEvent.keyDown(document.activeElement!, { key: 'End' });
  expect(end).toHaveAttribute('aria-valuenow', '120');
  fireEvent.click(screen.getByRole('button', { name: 'Save segment' }));
  await screen.findByText('Segment saved.');
  expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
    start_ms: 40_000,
    end_ms: 130_000,
  });
});

it('whole 45 second passage has no adjustable handles', async () => {
  setup({ ...segment, end_ms: 55_000 }, undefined, {
    ...session,
    passage: { start_ms: 10_000, end_ms: 55_000 },
  });
  await screen.findByText(
    'This passage is 60 seconds or shorter, so Shadow uses the whole passage.',
  );
  expect(screen.queryByRole('slider', { name: /Segment (start|end)/ })).not.toBeInTheDocument();
});

it('locked segment has no handles or save action', async () => {
  setup({ ...segment, locked_at: '2026-10-23T10:00:00Z' } as typeof segment);
  await screen.findByText('Segment locked. Round 1 has started.');
  expect(screen.queryByRole('slider', { name: /Segment (start|end)/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Save segment' })).not.toBeInTheDocument();
});

it('keeps the selection visible after a save refusal', async () => {
  setup(segment, problem(409, 'segment_locked', 'Segment locked by round 1.'));
  await screen.findByRole('slider', { name: 'Segment start' });
  fireEvent.click(screen.getByRole('button', { name: 'Save segment' }));
  await screen.findByText('Segment locked by round 1.');
  expect(screen.getByText(/4 marks/)).toBeInTheDocument();
});

it('shows a retry on a failed segment read', async () => {
  mockRoutes({
    [`GET ${path}`]: problem(503, 'unavailable', 'Try again later.'),
    'GET /contents/clip-1': jsonResponse(200, { media_url: null, peaks_url: null }),
  });
  renderWithProviders(<ShadowScreen session={session} progress={null} />);
  await waitFor(() => expect(screen.getByText('Try again later.')).toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});

it('holds the selected handles while a save is in flight', async () => {
  let resolveSave!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    resolveSave = resolve;
  });
  mockRoutes({
    [`GET ${path}`]: jsonResponse(200, segment),
    [`PUT ${path}`]: () => pending,
    'GET /contents/clip-1': jsonResponse(200, { media_url: null, peaks_url: null }),
  });
  renderWithProviders(<ShadowScreen session={session} progress={null} />);
  const start = await screen.findByRole('slider', { name: 'Segment start' });
  fireEvent.click(screen.getByRole('button', { name: 'Save segment' }));
  await screen.findByRole('button', { name: 'Saving…' });
  fireEvent.keyDown(start, { key: 'ArrowRight' });
  expect(start).toHaveAttribute('aria-valuenow', '0');
  resolveSave(jsonResponse(200, { ...segment, chosen_by: 'learner' }));
  await screen.findByText('Segment saved.');
});

it('replays the selected segment from its beginning', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  setup();
  await screen.findByRole('slider', { name: 'Segment start' });
  await waitFor(() => expect(document.querySelector('audio')).not.toBeNull());
  const audio = document.querySelector('audio')!;
  fireEvent.loadedMetadata(audio);
  fireEvent.change(screen.getByRole('slider', { name: 'Seek' }), { target: { value: '50000' } });
  expect(audio.currentTime).toBe(60);
  fireEvent.click(screen.getByRole('button', { name: 'Replay selected segment' }));
  expect(audio.currentTime).toBe(10);
});

it('draws passage peaks from a longer media file', async () => {
  mockRoutes({
    [`GET ${path}`]: jsonResponse(200, segment),
    'GET /contents/clip-1': jsonResponse(200, { media_url: null, peaks_url: '/api/v1/peaks' }),
    'GET /peaks': jsonResponse(200, {
      version: 1,
      per_second: 1,
      scale: 100,
      peaks: Array.from({ length: 200 }, () => 50),
    }),
  });
  renderWithProviders(<ShadowScreen session={session} progress={null} />);
  expect(await screen.findByTestId('waveform-bars')).toBeInTheDocument();
});

it('preview offers original speed only and repairs rate changes', async () => {
  setup();
  await screen.findByRole('slider', { name: 'Seek' });
  expect(screen.queryByRole('combobox', { name: /speed/i })).not.toBeInTheDocument();
  const audio = document.querySelector('audio')!;
  audio.playbackRate = 1.5;
  fireEvent.rateChange(audio);
  expect(audio.playbackRate).toBe(1);
});

it('requires saving edited segment handles before starting a round', async () => {
  mockRoutes({
    [`GET ${path}`]: jsonResponse(200, segment),
    [`PUT ${path}`]: (call) => jsonResponse(200, { ...segment, ...(call.body as object) }),
    [`GET /sessions/${session.id}/shadow/rounds`]: jsonResponse(200, {
      segment,
      current: null,
      rounds: [],
    }),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/audio', peaks_url: null }),
  });
  renderWithProviders(<ShadowScreen session={session} progress={null} />);
  const handle = await screen.findByRole('slider', { name: 'Segment start' });
  const start = await screen.findByRole('button', { name: 'Start round 1' });
  expect(start).toBeEnabled();
  fireEvent.keyDown(handle, { key: 'End' });
  expect(start).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Save segment' }));
  await screen.findByText('Segment saved.');
  expect(start).toBeEnabled();
});

it('uses the authoritative round segment while segment refresh is delayed', async () => {
  let number = 0;
  mockRoutes({
    [`GET ${path}`]: () => (number ? new Promise<Response>(() => {}) : jsonResponse(200, segment)),
    [`GET /sessions/${session.id}/shadow/rounds`]: () =>
      jsonResponse(200, {
        segment: { ...segment, locked_at: number ? '2026-10-25T10:00:00Z' : null },
        current: number
          ? { round: 1, transcript_shown: true, playback_status: 'ready', recorded_at: null }
          : null,
        rounds: [],
        ...(number ? { text: 'Round one text.' } : {}),
      }),
    [`POST /sessions/${session.id}/shadow/rounds/1/start`]: () => {
      number = 1;
      return new Response(null, { status: 204 });
    },
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/audio', peaks_url: null }),
  });
  renderWithProviders(<ShadowScreen session={session} progress={null} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Start round 1' }));
  await screen.findByRole('heading', { name: 'Round 1 of 3' });
  expect(document.querySelectorAll('audio')).toHaveLength(1);
  expect(screen.getByText('Segment locked. Round 1 has started.')).toBeInTheDocument();
});
