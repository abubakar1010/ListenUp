import { fireEvent, screen, within } from '@testing-library/react';
import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import { mockRoutes } from '../session/testApi';
import { ShadowCompletion } from './ShadowCompletion';

afterEach(() => vi.restoreAllMocks());

function round(n: number, available: boolean) {
  return {
    id: `r${n}`,
    round: n,
    transcript_shown: n === 1,
    playback_status: 'ended',
    recorded_at: '2026-10-27T10:00:00Z',
    recording_available: available,
    feedback: 'unavailable',
  };
}

function routes(deleteAnswer: () => Response) {
  let deleted = false;
  const mocked = mockRoutes({
    'GET /sessions/session-1/shadow/rounds': () =>
      jsonResponse(200, {
        segment: { start_ms: 0, end_ms: 60000 },
        current: round(3, true),
        rounds: [round(1, !deleted), round(2, true), round(3, true)],
      }),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/original' }),
    'DELETE /shadow/rounds/r1/recording': () => {
      const answer = deleteAnswer();
      if (answer.ok) deleted = true;
      return answer;
    },
  });
  renderWithProviders(<ShadowCompletion session={sessionFixture({ done: 4 })} />);
  return mocked;
}

test('one recording is deleted after confirming; the round stays recorded (FR-SH-17)', async () => {
  const { calls } = routes(() => new Response(null, { status: 204 }));
  const replay = await screen.findByRole('region', { name: 'Round 1 replay' });
  fireEvent.click(within(replay).getByRole('button', { name: 'Delete recording of round 1' }));
  const dialog = screen.getByRole('dialog', { name: 'Delete your recording of round 1?' });
  expect(dialog).toHaveTextContent(/keeps its place in the plan/);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep recording' }));
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false);

  fireEvent.click(within(replay).getByRole('button', { name: 'Delete recording of round 1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete recording' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Recording of round 1 deleted.');
  await vi.waitFor(() =>
    expect(screen.queryByRole('region', { name: 'Round 1 replay' })).not.toBeInTheDocument(),
  );
  expect(screen.getByRole('region', { name: 'Round 2 replay' })).toBeInTheDocument();
  expect(screen.getByText('Three Shadow rounds recorded.')).toBeInTheDocument();
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1);
});

test('a failed recording deletion keeps the dialog with the error', async () => {
  routes(() => problem(503, 'unavailable', 'Try again shortly.'));
  const replay = await screen.findByRole('region', { name: 'Round 1 replay' });
  fireEvent.click(within(replay).getByRole('button', { name: 'Delete recording of round 1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete recording' }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Round 1 replay' })).toBeInTheDocument();
});
