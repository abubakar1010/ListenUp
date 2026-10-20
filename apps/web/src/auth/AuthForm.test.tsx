import { fireEvent, screen } from '@testing-library/react';

import { App } from '../App';
import {
  jsonResponse,
  LEARNER,
  mockApi,
  problem,
  renderWithProviders,
  SIGNED_OUT,
} from '../test-utils';

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

async function fillAndSubmit(button: string) {
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'learner@example.com' },
  });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse' } });
  fireEvent.click(screen.getByRole('button', { name: button }));
}

test('signing in sends the CSRF token and goes to the library', async () => {
  let signedIn = false;
  const fetchMock = mockApi({
    '/me': () => (signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT()),
    '/auth/login': () => {
      signedIn = true;
      return jsonResponse(200, LEARNER);
    },
  });
  renderWithProviders(<App />, { route: '/sign-in' });

  await fillAndSubmit('Sign in');

  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
  const login = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/login');
  const init = login?.[1];
  expect(init?.method).toBe('POST');
  expect((init?.headers as Record<string, string>)['X-CSRF-Token']).toBe('token-123');
  expect(JSON.parse(String(init?.body))).toEqual({
    email: 'learner@example.com',
    password: 'correct horse',
  });
});

test('a locked account is announced with the time it can try again', async () => {
  const lockedUntil = '2026-10-03T10:45:00Z';
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/login': () =>
      problem(429, 'account_locked', 'Too many failed sign-in attempts.', {
        locked_until: lockedUntil,
      }),
  });
  renderWithProviders(<App />, { route: '/sign-in' });

  await fillAndSubmit('Sign in');

  const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(
    new Date(lockedUntil),
  );
  expect(await screen.findByText(`You can try again at ${time}.`, { exact: false })).toHaveRole(
    'alert',
  );
});

test('the server message explains a failed registration', async () => {
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/consent-versions': jsonResponse(200, {
      terms: 'terms-1',
      privacy: 'privacy-1',
      voice_recording: 'voice-1',
    }),
    '/auth/register': () =>
      problem(409, 'email_taken', 'An account with this email already exists. Sign in instead.'),
  });
  renderWithProviders(<App />, { route: '/register' });
  fireEvent.click(await screen.findByRole('checkbox', { name: /I agree to the Terms/ }));

  await fillAndSubmit('Create account');

  expect(
    await screen.findByText('An account with this email already exists.', { exact: false }),
  ).toHaveRole('alert');
});

test('the form fields have labels and the password hint is linked', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/register' });

  const password = await screen.findByLabelText('Password');
  expect(password).toHaveAttribute('autocomplete', 'new-password');
  expect(password).toHaveAccessibleDescription('At least 8 characters.');
  expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email');
});

describe('signing in to a deleted account (#120)', () => {
  const until = '2026-10-11T20:30:00Z';
  const pending = () =>
    problem(409, 'account_pending_deletion', 'This account was deleted.', {
      deletion_scheduled_at: until,
    });

  test('asks before restoring, with the date the data goes', async () => {
    let signedIn = false;
    const bodies: unknown[] = [];
    mockApi({
      '/me': () => (signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT()),
      '/auth/login': () => pending(),
    });
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input).replace(/^\/api\/v1/, '');
      if (path === '/me') return signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT();
      if (path === '/auth/login') {
        const body = JSON.parse(String(init?.body)) as { restore?: boolean };
        bodies.push(body);
        if (!body.restore) return pending();
        signedIn = true;
        return jsonResponse(200, LEARNER);
      }
      return problem(404, 'not_found', path);
    });
    renderWithProviders(<App />, { route: '/sign-in' });

    await fillAndSubmit('Sign in');

    const dialog = await screen.findByRole('dialog', { name: 'Restore your account?' });
    const date = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'full',
      timeStyle: 'short',
    }).format(new Date(until));
    expect(dialog).toHaveTextContent(date);
    // The safe action keeps things as they are.
    expect(screen.getByRole('button', { name: 'Keep it deleted' })).toHaveFocus();
    expect(screen.getByRole('alert')).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole('button', { name: 'Restore my account' }));

    expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
    expect(bodies).toEqual([
      { email: 'learner@example.com', password: 'correct horse' },
      { email: 'learner@example.com', password: 'correct horse', restore: true },
    ]);
  });

  test('declining keeps the account deleted and signs nobody in', async () => {
    const fetchMock = mockApi({ '/me': SIGNED_OUT, '/auth/login': () => pending() });
    renderWithProviders(<App />, { route: '/sign-in' });

    await fillAndSubmit('Sign in');
    fireEvent.click(await screen.findByRole('button', { name: 'Keep it deleted' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Your account stays deleted');
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/v1/auth/login')).toHaveLength(1);
  });

  test('a restore refused because the grace period ended shows the normal message', async () => {
    let calls = 0;
    mockApi({
      '/me': SIGNED_OUT,
      '/auth/login': () =>
        ++calls === 1
          ? pending()
          : problem(401, 'invalid_credentials', 'The email or password is wrong.'),
    });
    renderWithProviders(<App />, { route: '/sign-in' });

    await fillAndSubmit('Sign in');
    fireEvent.click(await screen.findByRole('button', { name: 'Restore my account' }));

    expect(await screen.findByText('The email or password is wrong.')).toHaveRole('alert');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

test('Google sign-in has an accessible link on /sign-in', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/sign-in?next=%2Fsettings' });
  expect(await screen.findByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    '/api/v1/auth/oidc/google/start?next=%2Fsettings',
  );
});

test('Google sign-up on /register keeps next once the terms are accepted (#104)', async () => {
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/consent-versions': jsonResponse(200, { terms: 't', privacy: 'p', voice_recording: 'v' }),
  });
  renderWithProviders(<App />, { route: '/register?next=%2Fsettings' });
  fireEvent.click(await screen.findByRole('checkbox', { name: /I agree to the Terms/ }));
  expect(await screen.findByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    '/api/v1/auth/oidc/google/start?next=%2Fsettings&terms_version=t&privacy_version=p',
  );
});

test('Google restoration asks explicitly and keeping deleted sends no restore', async () => {
  const calls: boolean[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).endsWith('/me')) return SIGNED_OUT();
    if (init?.method === 'POST') {
      calls.push(JSON.parse(String(init.body)).restore);
      return new Response(null, { status: 204 });
    }
    return jsonResponse(200, { deletion_scheduled_at: '2026-10-23T12:00:00Z' });
  });
  renderWithProviders(<App />, { route: '/sign-in?google=restore' });
  expect(await screen.findByRole('dialog', { name: 'Restore your account?' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Keep it deleted' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Your account stays deleted');
  expect(calls).toEqual([false]);
});

test('Google restoration publishes the new session only after explicit Restore', async () => {
  let restored = false;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).endsWith('/me')) return restored ? jsonResponse(200, LEARNER) : SIGNED_OUT();
    if (String(input).includes('/oidc/google/restore')) {
      if (init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({ restore: true });
        restored = true;
        return jsonResponse(200, LEARNER);
      }
      return jsonResponse(200, { deletion_scheduled_at: '2026-10-23T12:00:00Z' });
    }
    return jsonResponse(200, { items: [] });
  });
  renderWithProviders(<App />, { route: '/sign-in?google=restore' });
  expect(await screen.findByRole('dialog', { name: 'Restore your account?' })).toBeInTheDocument();
  expect(restored).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Restore my account' }));
  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
});

test('Google cancellation is announced and permits retry', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/sign-in?google=cancelled' });
  expect(await screen.findByRole('status')).toHaveTextContent('Google sign-in was cancelled');
  expect(screen.getByRole('link', { name: 'Continue with Google' })).toBeInTheDocument();
});

test('an expired Google restoration is explained without unlocking the account', async () => {
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/oidc/google/restore': () =>
      problem(400, 'google_auth_failed', 'Start Google sign-in again.'),
  });
  renderWithProviders(<App />, { route: '/sign-in?google=restore' });
  expect(await screen.findByText('Start Google sign-in again.')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('a restore refusal closes the dialog so Google authentication can start again', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).endsWith('/me')) return SIGNED_OUT();
    if (init?.method === 'POST')
      return problem(400, 'google_auth_failed', 'Google confirmation expired. Try again.');
    return jsonResponse(200, {
      deletion_scheduled_at: '2026-10-23T12:00:00Z',
      next_path: '/library',
    });
  });
  renderWithProviders(<App />, { route: '/sign-in?google=restore' });
  fireEvent.click(await screen.findByRole('button', { name: 'Restore my account' }));
  expect(await screen.findByText('Google confirmation expired. Try again.')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Continue with Google' })).toBeVisible();
});

test.each([
  ['/auth/google-error?reason=failed&intent=login', '/api/v1/auth/oidc/google/start'],
  [
    '/auth/google-error?reason=fresh_auth&intent=reauth',
    '/api/v1/auth/oidc/google/start?purpose=reauth',
  ],
])('Google callback recovery at %s offers a new flow', async (route, target) => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route });
  expect(
    await screen.findByRole('heading', { name: 'Google confirmation was not completed' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    target,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('Your account has not been deleted');
});

test('stale Google authentication explains signing out separately without logging out ListenUp', async () => {
  mockApi({ '/me': () => jsonResponse(200, LEARNER) });
  renderWithProviders(<App />, { route: '/auth/google-error?reason=fresh_auth&intent=reauth' });
  expect(
    await screen.findByText(/Sign out of your Google Account in another tab/),
  ).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    '/api/v1/auth/oidc/google/start?purpose=reauth',
  );
});
