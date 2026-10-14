import { screen } from '@testing-library/react';

import { App } from '../../App';
import { LEARNER, jsonResponse, problem, renderWithProviders } from '../../test-utils';

const ROUTE = '/account-deleted?until=2026-10-11T20%3A30%3A00Z';

afterEach(() => vi.restoreAllMocks());

function mockMe(signedIn: boolean) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    if (path === '/me') {
      return signedIn ? jsonResponse(200, LEARNER) : problem(401, 'not_signed_in', 'Sign in.');
    }
    return jsonResponse(200, { items: [], next_cursor: null });
  });
}

test('says the account is deleted to someone who is signed out', async () => {
  mockMe(false);
  renderWithProviders(<App />, { route: ROUTE });

  expect(
    await screen.findByRole('heading', { name: 'Your account is deleted' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Go to sign in' })).toBeVisible();
});

test('sends a learner who restored the account to the library instead', async () => {
  mockMe(true);
  renderWithProviders(<App />, { route: ROUTE });

  expect(await screen.findByRole('heading', { name: /library/i })).toBeInTheDocument();
  expect(screen.queryByText('Your account is deleted')).not.toBeInTheDocument();
});
