import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes } from '../session/testApi';
import { useUploadRecording } from './api';

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
    'GET /sessions/session-1/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: null,
      rounds: [],
    }),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/original' }),
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
  expect(screen.getByText('Feedback unavailable.')).toBeInTheDocument();
  expect(calls.find((c) => c.path === '/shadow/rounds/r3/complete')?.body).toEqual({ version: 3 });
  expect(calls.some((c) => /grades|retry/.test(c.path))).toBe(false);
});
