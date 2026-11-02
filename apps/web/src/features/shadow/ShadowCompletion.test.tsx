import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes } from '../session/testApi';
import { useUploadRecording } from './api';
import { roundFixture, SCORED_ROUND } from './fixtures';

function SubmitRecording() {
  const upload = useUploadRecording('session-1');
  return (
    <button
      onClick={() =>
        upload.mutate({ number: 3, recording: { blob: new Blob(['voice']), mime: 'audio/webm' } })
      }
    >
      Send held recording
    </button>
  );
}

afterEach(() => vi.restoreAllMocks());

test('final upload refreshes the authoritative session and shows completion without grading', async () => {
  let completed = false;
  const { calls } = mockRoutes({
    'GET /sessions/session-1': () => jsonResponse(200, sessionFixture({ done: completed ? 4 : 3 })),
    'GET /sessions/session-1/shadow/segment': jsonResponse(200, {
      session_id: 'session-1',
      start_ms: 0,
      end_ms: 60000,
      chosen_by: 'system',
      mark_count: 0,
      locked_at: 'now',
    }),
    'GET /sessions/session-1/shadow/rounds': () =>
      jsonResponse(200, {
        segment: { start_ms: 0, end_ms: 60000 },
        current: null,
        rounds: completed ? [1, 2, 3].map((round) => roundFixture(round)) : [],
      }),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/original' }),
    'GET /shadow/rounds/r1/grade': jsonResponse(200, { status: 'unavailable' }),
    'GET /shadow/rounds/r2/grade': jsonResponse(200, { status: 'unavailable' }),
    'GET /shadow/rounds/r3/grade': jsonResponse(200, { status: 'unavailable' }),
    'POST /sessions/session-1/shadow/rounds/3/recording': jsonResponse(200, {
      round_id: 'r3',
      upload: { url: 'https://storage.test/put', method: 'PUT', headers: {} },
    }),
    'PUT https://storage.test/put': new Response(null, { status: 200 }),
    'POST /shadow/rounds/r3/complete': () => {
      completed = true;
      return new Response(null, { status: 204 });
    },
  });
  renderWithProviders(
    <>
      <SubmitRecording />
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionPage />} />
      </Routes>
    </>,
    { route: '/sessions/session-1' },
  );
  await screen.findByText('Step 4 of 4');
  fireEvent.click(screen.getByRole('button', { name: 'Send held recording' }));
  expect(await screen.findByText('All 4 steps finished')).toBeInTheDocument();
  await waitFor(() => expect(screen.getAllByText('Feedback unavailable.')).toHaveLength(3));
  expect(calls.find((c) => c.path === '/shadow/rounds/r3/complete')?.body).toEqual({ version: 3 });
  expect(calls.some((c) => /grades|retry/.test(c.path))).toBe(false);
});

test("round 3 word markers show on the completion screen, with every round's feedback", async () => {
  mockRoutes({
    'GET /sessions/session-1': jsonResponse(200, sessionFixture({ done: 4 })),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/original' }),
    'GET /sessions/session-1/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: null,
      rounds: [
        roundFixture(1, { recording_available: false, feedback: null }),
        roundFixture(2),
        roundFixture(3),
      ],
    }),
    'GET /shadow/rounds/r1/grade': jsonResponse(200, { status: 'unavailable' }),
    'GET /shadow/rounds/r2/grade': jsonResponse(200, { status: 'unavailable' }),
    'GET /shadow/rounds/r3/grade': jsonResponse(200, SCORED_ROUND),
  });
  renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: '/sessions/session-1' },
  );
  expect(await screen.findByRole('region', { name: 'Round 3 word markers' })).toBeVisible();
  expect(screen.getByRole('region', { name: 'Round 3 accent guidance' })).toBeVisible();
  // Round 1's recording is gone, but its feedback stays (D7).
  const first = screen.getByRole('region', { name: 'Round 1' });
  expect(within(first).getByText('Feedback unavailable.')).toBeInTheDocument();
  expect(screen.getAllByText('Feedback unavailable.')).toHaveLength(2);
});
