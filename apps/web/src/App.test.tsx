import { screen } from '@testing-library/react';

import { App } from './App';
import { jsonResponse, problem, renderWithProviders } from './test-utils';

afterEach(() => vi.restoreAllMocks());

test('shows the product name', () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(401, 'not_signed_in', 'Sign in to continue.'),
  );
  renderWithProviders(<App />);

  expect(screen.getByRole('heading', { name: 'ListenUp' })).toBeInTheDocument();
});

test('offers sign-in when nobody is signed in', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(401, 'not_signed_in', 'Sign in to continue.'),
  );
  renderWithProviders(<App />);

  expect(await screen.findByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in');
});

test('shows who is signed in', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(200, {
      id: '1',
      email: 'learner@example.com',
      display_name: null,
      email_verified: false,
    }),
  );
  renderWithProviders(<App />);

  expect(await screen.findByText('Signed in as learner@example.com')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
});
