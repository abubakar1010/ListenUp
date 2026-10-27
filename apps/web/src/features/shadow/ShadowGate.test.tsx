import { fireEvent, screen } from '@testing-library/react';
import { jsonResponse, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { ShadowRounds } from './ShadowRounds';

it('blocks start, saved-round playback and retry until microphone and consent are ready', async () => {
  const { calls } = mockRoutes({
    'GET /sessions/s/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: null,
      rounds: [],
    }),
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, { consents: [] }),
  });
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  const start = await screen.findByRole('button', { name: 'Start round 1' });
  expect(start).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(start);
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
  expect(screen.queryByRole('button', { name: 'Play round 1' })).not.toBeInTheDocument();
});

it('requires a fresh microphone check when resuming an existing round', async () => {
  mockRoutes({
    'GET /sessions/s/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 0, end_ms: 60000 },
      current: { round: 1, playback_status: 'ready' },
      rounds: [],
    }),
    'GET /contents/c': jsonResponse(200, { media_url: '/audio' }),
    'GET /auth/consent-versions': jsonResponse(200, { voice_recording: 'voice-2026-1' }),
    'GET /me/consents': jsonResponse(200, {
      consents: [{ kind: 'voice_recording', version: 'voice-2026-1', withdrawn_at: null }],
    }),
  });
  renderWithProviders(<ShadowRounds sessionId="s" contentId="c" />);
  await screen.findByText(/You agreed to this version/);
  expect(screen.getAllByRole('status')).toHaveLength(1);
  expect(screen.queryByRole('button', { name: 'Play round 1' })).not.toBeInTheDocument();
});
