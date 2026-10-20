import { fireEvent, screen, within } from '@testing-library/react';

import { App } from '../../App';
import { jsonResponse, LEARNER, mockApi, problem, renderWithProviders } from '../../test-utils';

// #104: the settings page lists consents and withdraws voice-recording consent.

const CURRENT = { terms: 'terms-2', privacy: 'privacy-1', voice_recording: 'voice-1' };
const AT = '2026-10-01T09:00:00Z';

function record(
  kind: string,
  version: string,
  current: boolean,
  withdrawn_at: string | null = null,
) {
  return { kind, version, granted_at: AT, withdrawn_at, current };
}

const WITH_VOICE = {
  current: CURRENT,
  consents: [
    record('voice_recording', 'voice-1', true),
    record('terms', 'terms-2', true),
    record('terms', 'terms-1', false),
    record('privacy', 'privacy-1', true),
  ],
};

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

function mockSettings(consents: object, withdraw?: () => Response) {
  return mockApi({
    '/me': jsonResponse(200, LEARNER),
    '/me/exports/latest': jsonResponse(200, { export: null }),
    '/me/consents': jsonResponse(200, consents),
    ...(withdraw ? { '/me/consents/withdraw': withdraw } : {}),
  });
}

async function section() {
  const heading = await screen.findByRole('heading', { name: 'Agreements', level: 2 });
  return heading.closest('section') as HTMLElement;
}

test('lists the accepted versions and which ones are current', async () => {
  mockSettings(WITH_VOICE);
  renderWithProviders(<App />, { route: '/settings' });

  const agreements = await section();
  expect(
    await within(agreements).findByText('Terms of Service, version terms-2'),
  ).toBeInTheDocument();
  expect(
    within(agreements).getByText('Terms of Service, version terms-1 (earlier version)'),
  ).toBeInTheDocument();
  expect(within(agreements).getByText('Privacy Policy, version privacy-1')).toBeInTheDocument();
  expect(
    within(agreements).getByText('Voice recording consent, version voice-1'),
  ).toBeInTheDocument();
});

test('withdrawing voice consent asks first, then shows it withdrawn', async () => {
  const fetchMock = mockSettings(WITH_VOICE, () =>
    jsonResponse(200, {
      current: CURRENT,
      consents: WITH_VOICE.consents.map((c) =>
        c.kind === 'voice_recording' ? { ...c, withdrawn_at: '2026-10-19T10:00:00Z' } : c,
      ),
    }),
  );
  renderWithProviders(<App />, { route: '/settings' });

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw voice recording consent' }));
  const dialog = await screen.findByRole('dialog', { name: 'Withdraw voice recording consent?' });
  expect(within(dialog).getByRole('button', { name: 'Keep my consent' })).toHaveFocus();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw consent' }));

  expect(await screen.findByText(/You withdrew voice recording consent/)).toHaveRole('status');
  expect(
    screen.queryByRole('button', { name: 'Withdraw voice recording consent' }),
  ).not.toBeInTheDocument();
  const withdraws = fetchMock.mock.calls.filter(([url]) => url === '/api/v1/me/consents/withdraw');
  expect(withdraws.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    { kind: 'voice_recording' },
  ]);
});

test('cancelling the question withdraws nothing', async () => {
  const fetchMock = mockSettings(WITH_VOICE, () => jsonResponse(200, WITH_VOICE));
  renderWithProviders(<App />, { route: '/settings' });

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw voice recording consent' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Keep my consent' }));

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/me/consents/withdraw')).toBe(false);
});

test('a failed withdrawal says so and keeps the consent shown', async () => {
  mockSettings(WITH_VOICE, () => problem(503, 'unavailable', 'ListenUp is busy. Try again.'));
  renderWithProviders(<App />, { route: '/settings' });

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw voice recording consent' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw consent' }));

  expect(await screen.findByText('ListenUp is busy. Try again.')).toHaveRole('alert');
});

test('without voice consent there is nothing to withdraw', async () => {
  mockSettings({
    current: CURRENT,
    consents: [record('terms', 'terms-2', true), record('privacy', 'privacy-1', true)],
  });
  renderWithProviders(<App />, { route: '/settings' });

  const agreements = await section();
  expect(
    await within(agreements).findByText(/You have not agreed to voice recording/),
  ).toBeInTheDocument();
  expect(within(agreements).queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument();
});
