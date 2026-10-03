import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../test-utils';
import { SignInPage } from './pages';
import { PasswordResetConfirmPage, PasswordResetRequestPage } from './PasswordResetPages';

const SENT =
  'If an account uses this email, we have sent it a link to reset the password. ' +
  'The link works once. Check your inbox and spam folder.';

function Pages() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/forgot-password" element={<PasswordResetRequestPage />} />
      <Route path="/reset-password" element={<PasswordResetConfirmPage />} />
    </Routes>
  );
}

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

test('the sign-in page links to the reset request', () => {
  renderWithProviders(<Pages />, { route: '/sign-in' });

  fireEvent.click(screen.getByRole('link', { name: 'Forgot your password?' }));

  expect(screen.getByRole('heading', { name: 'Reset your password' })).toBeInTheDocument();
});

test('asking for a reset sends the email with the CSRF token and shows the same answer', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(jsonResponse(202, { detail: SENT }));
  renderWithProviders(<Pages />, { route: '/forgot-password' });

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'learner@example.com' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));

  expect(await screen.findByRole('status')).toHaveTextContent(SENT);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/auth/password-reset');
  expect(init?.method).toBe('POST');
  expect((init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('token-123');
  expect(JSON.parse(String(init?.body))).toEqual({ email: 'learner@example.com' });
});

test('a rate-limited request is announced', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(429, 'rate_limited', 'Too many requests. Try again later.'),
  );
  renderWithProviders(<Pages />, { route: '/forgot-password' });

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'learner@example.com' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests.');
});

test('the token from the link fragment is sent with the new password', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(204));
  renderWithProviders(<Pages />, { route: '/reset-password#token=abc_DEF-123' });

  const password = screen.getByLabelText('New password');
  expect(password).toHaveAttribute('autocomplete', 'new-password');
  expect(password).toHaveAccessibleDescription('At least 8 characters.');
  fireEvent.change(password, { target: { value: 'a brand new passphrase' } });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Your password has been changed and you have been signed out everywhere.',
  );
  expect(screen.getByRole('link', { name: 'Sign in with your new password' })).toHaveAttribute(
    'href',
    '/sign-in',
  );
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/auth/password-reset/confirm');
  expect(JSON.parse(String(init?.body))).toEqual({
    token: 'abc_DEF-123',
    password: 'a brand new passphrase',
  });
});

test('a used or expired link explains itself and offers a new one', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(
      400,
      'invalid_reset_link',
      'This reset link has expired or was already used. Ask for a new link from the sign-in page.',
    ),
  );
  renderWithProviders(<Pages />, { route: '/reset-password#token=old' });

  fireEvent.change(screen.getByLabelText('New password'), {
    target: { value: 'a brand new passphrase' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('This reset link has expired or was already used.');
  expect(screen.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute(
    'href',
    '/forgot-password',
  );
});

test('a weak password is marked on the field', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(422, 'weak_password', 'Use at least 8 characters for your password.'),
  );
  renderWithProviders(<Pages />, { route: '/reset-password#token=abc' });

  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'short' } });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('Use at least 8 characters');
  expect(screen.getByLabelText('New password')).toHaveAttribute('aria-invalid', 'true');
});

test('a link without a token says what to do', () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch');
  renderWithProviders(<Pages />, { route: '/reset-password' });

  expect(screen.getByRole('alert')).toHaveTextContent('This reset link is incomplete.');
  expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});
