import { fireEvent, screen } from '@testing-library/react';

import { App } from '../App';
import { jsonResponse, problem, renderWithProviders } from '../test-utils';

const ME = { id: '1', email: 'learner@example.com', display_name: null, email_verified: false };

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

function fillAndSubmit(button: string) {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'learner@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse' } });
  fireEvent.click(screen.getByRole('button', { name: button }));
}

test('signing in sends the CSRF token and goes home signed in', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input) =>
      String(input).endsWith('/auth/login') ? jsonResponse(200, ME) : jsonResponse(200, ME),
    );
  renderWithProviders(<App />, { route: '/sign-in' });

  fillAndSubmit('Sign in');

  expect(await screen.findByText('Signed in as learner@example.com')).toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/auth/login');
  expect(init?.method).toBe('POST');
  expect((init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('token-123');
  expect(JSON.parse(String(init?.body))).toEqual({
    email: 'learner@example.com',
    password: 'correct horse',
  });
});

test('a locked account is announced with the time it can try again', async () => {
  const lockedUntil = '2026-10-03T10:45:00Z';
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(429, 'account_locked', 'Too many failed sign-in attempts.', {
      locked_until: lockedUntil,
    }),
  );
  renderWithProviders(<App />, { route: '/sign-in' });

  fillAndSubmit('Sign in');

  const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(
    new Date(lockedUntil),
  );
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(`You can try again at ${time}.`);
});

test('the server message explains a failed registration', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(409, 'email_taken', 'An account with this email already exists. Sign in instead.'),
  );
  renderWithProviders(<App />, { route: '/register' });

  fillAndSubmit('Create account');

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'An account with this email already exists.',
  );
});

test('the form fields have labels and the password hint is linked', () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(200, ME));
  renderWithProviders(<App />, { route: '/register' });

  const password = screen.getByLabelText('Password');
  expect(password).toHaveAttribute('autocomplete', 'new-password');
  expect(password).toHaveAccessibleDescription('At least 8 characters.');
  expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email');
});
