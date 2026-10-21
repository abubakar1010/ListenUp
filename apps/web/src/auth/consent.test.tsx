import { fireEvent, screen, within } from '@testing-library/react';

import { App } from '../App';
import {
  jsonResponse,
  LEARNER,
  mockApi,
  problem,
  renderWithProviders,
  SIGNED_OUT,
} from '../test-utils';

// #104: sign-up accepts the current terms and privacy versions; a newer version is
// asked for once on the next sign-in.

const VERSIONS = { terms: 'terms-1', privacy: 'privacy-1', voice_recording: 'voice-1' };

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

async function fillRegistration() {
  fireEvent.change(await screen.findByLabelText('Email'), {
    target: { value: 'learner@example.com' },
  });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse' } });
  await waitForVersions();
}

function acceptBox() {
  return screen.getByRole('checkbox', { name: /I agree to the Terms of Service/ });
}

/** The box can be ticked once the versions it accepts are shown. */
async function waitForVersions() {
  await vi.waitFor(() => expect(acceptBox()).toBeEnabled());
}

function registerCalls(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls.filter(([url]) => url === '/api/v1/auth/register');
}

test('creating an account without accepting the terms is stopped before it is sent', async () => {
  const fetchMock = mockApi({
    '/me': SIGNED_OUT,
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
  });
  renderWithProviders(<App />, { route: '/register' });
  await fillRegistration();

  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect(
    await screen.findByText('Accept the Terms of Service and Privacy Policy to create an account.'),
  ).toHaveRole('alert');
  expect(acceptBox()).toHaveAttribute('aria-invalid', 'true');
  expect(registerCalls(fetchMock)).toHaveLength(0);
});

test('accepting sends the versions the learner was shown', async () => {
  let signedIn = false;
  const fetchMock = mockApi({
    '/me': () => (signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT()),
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
    '/auth/register': () => {
      signedIn = true;
      return jsonResponse(201, LEARNER);
    },
  });
  renderWithProviders(<App />, { route: '/register' });
  await fillRegistration();
  expect(screen.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', '/terms');
  expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/privacy');

  fireEvent.click(acceptBox());
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
  const [call] = registerCalls(fetchMock);
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    email: 'learner@example.com',
    password: 'correct horse',
    terms_version: 'terms-1',
    privacy_version: 'privacy-1',
  });
});

test('a version published while the form was open asks the learner to accept again', async () => {
  let versions = VERSIONS;
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/consent-versions': () => jsonResponse(200, versions),
    '/auth/register': () => {
      versions = { ...VERSIONS, terms: 'terms-2' };
      return problem(409, 'consent_version_changed', 'The terms changed. Accept them again.', {
        current: versions,
      });
    },
  });
  renderWithProviders(<App />, { route: '/register' });
  await fillRegistration();
  fireEvent.click(acceptBox());

  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect(await screen.findByText('The terms changed. Accept them again.')).toHaveRole('alert');
  expect(acceptBox()).not.toBeChecked();
});

test('continuing with Google on the register page needs the same acceptance', async () => {
  mockApi({ '/me': SIGNED_OUT, '/auth/consent-versions': jsonResponse(200, VERSIONS) });
  renderWithProviders(<App />, { route: '/register' });
  await fillRegistration();

  fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
  expect(
    await screen.findByText('Accept the Terms of Service and Privacy Policy to create an account.'),
  ).toHaveRole('alert');

  fireEvent.click(acceptBox());
  const google = await screen.findByRole('link', { name: 'Continue with Google' });
  const url = new URL(google.getAttribute('href') ?? '', 'http://localhost');
  expect(url.pathname).toBe('/api/v1/auth/oidc/google/start');
  expect(url.searchParams.get('terms_version')).toBe('terms-1');
  expect(url.searchParams.get('privacy_version')).toBe('privacy-1');
});

test('signing in with Google needs no acceptance', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/sign-in' });

  const google = await screen.findByRole('link', { name: 'Continue with Google' });

  expect(google.getAttribute('href')).not.toContain('terms_version');
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});

test('a Google sign-up refused for consent points to the create-account page', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/auth/google-error?reason=consent&intent=login' });

  expect(
    await screen.findByText(/To create an account with Google, first accept the Terms of Service/),
  ).toHaveRole('alert');
  expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
    'href',
    '/register',
  );
});

test('a newer terms version is asked for once before the app opens', async () => {
  let required: string[] = ['terms'];
  const fetchMock = mockApi({
    '/me': () => jsonResponse(200, { ...LEARNER, consents_required: required }),
    '/auth/consent-versions': jsonResponse(200, { ...VERSIONS, terms: 'terms-2' }),
    '/me/consents': () => {
      required = [];
      return jsonResponse(200, { current: VERSIONS, consents: [] });
    },
    '/contents': jsonResponse(200, { items: [], next_cursor: null }),
  });
  renderWithProviders(<App />, { route: '/library' });

  const prompt = await screen.findByRole('heading', { name: 'We updated our Terms of Service' });
  expect(screen.queryByRole('heading', { name: 'Library' })).not.toBeInTheDocument();
  const main = prompt.closest('main');
  expect(main).not.toBeNull();
  expect(
    within(main as HTMLElement).getByRole('link', { name: 'Terms of Service' }),
  ).toHaveAttribute('href', '/terms');

  expect(await screen.findByText('(version terms-2)', { exact: false })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Accept and continue' }));

  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
  const grants = fetchMock.mock.calls.filter(([url]) => url === '/api/v1/me/consents');
  expect(grants.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    { kind: 'terms', version: 'terms-2' },
  ]);
});

test('the learner may sign out instead of accepting', async () => {
  let signedIn = true;
  mockApi({
    '/me': () =>
      signedIn ? jsonResponse(200, { ...LEARNER, consents_required: ['privacy'] }) : SIGNED_OUT(),
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
    '/auth/logout': () => {
      signedIn = false;
      return jsonResponse(204);
    },
  });
  renderWithProviders(<App />, { route: '/library' });

  await screen.findByRole('heading', { name: 'We updated our Privacy Policy' });
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
});

test('the placeholder documents say they are placeholders', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/terms' });

  expect(await screen.findByRole('heading', { name: 'Terms of Service' })).toBeInTheDocument();
  expect(screen.getByText(/Placeholder/)).toBeInTheDocument();
});

test('a version published while the prompt is open is shown and asked for again', async () => {
  let terms = 'terms-2';
  mockApi({
    '/me': () => jsonResponse(200, { ...LEARNER, consents_required: ['terms'] }),
    '/auth/consent-versions': () => jsonResponse(200, { ...VERSIONS, terms }),
    '/me/consents': () => {
      terms = 'terms-3';
      return problem(409, 'consent_version_changed', 'The terms changed again. Read them first.');
    },
  });
  renderWithProviders(<App />, { route: '/library' });
  await screen.findByText('(version terms-2)', { exact: false });

  fireEvent.click(screen.getByRole('button', { name: 'Accept and continue' }));

  expect(await screen.findByText('The terms changed again. Read them first.')).toHaveRole('alert');
  expect(await screen.findByText('(version terms-3)', { exact: false })).toBeInTheDocument();
});

test('the privacy placeholder states the product rule on learner data', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderWithProviders(<App />, { route: '/privacy' });

  expect(await screen.findByRole('heading', { name: 'Privacy Policy' })).toBeInTheDocument();
  expect(screen.getByText(/never used to train AI models/)).toBeInTheDocument();
});

test('the register form shows the versions it asks the learner to accept', async () => {
  mockApi({ '/me': SIGNED_OUT, '/auth/consent-versions': jsonResponse(200, VERSIONS) });
  renderWithProviders(<App />, { route: '/register' });

  expect(
    await screen.findByText('Terms of Service version terms-1, Privacy Policy version privacy-1.'),
  ).toBeInTheDocument();
  expect(acceptBox()).toBeEnabled();
});

test('while the versions load, neither sign-up path can be accepted yet', async () => {
  const never = (() => new Promise<Response>(() => {})) as unknown as () => Response;
  mockApi({ '/me': SIGNED_OUT, '/auth/consent-versions': never });
  renderWithProviders(<App />, { route: '/register' });

  expect(
    await screen.findByText('Loading the current Terms of Service and Privacy Policy…'),
  ).toHaveRole('status');
  expect(acceptBox()).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeDisabled();
});

test('when the versions fail to load, the register page says so and can retry', async () => {
  let fail = true;
  mockApi({
    '/me': SIGNED_OUT,
    '/auth/consent-versions': () =>
      fail
        ? problem(503, 'service_unavailable', 'The service is down.')
        : jsonResponse(200, VERSIONS),
  });
  renderWithProviders(<App />, { route: '/register' });
  const retry = await screen.findByRole('button', { name: 'Try again' });
  expect(acceptBox()).toBeDisabled();

  fail = false;
  fireEvent.click(retry);

  await waitForVersions();
  fireEvent.click(acceptBox());
  expect(await screen.findByRole('link', { name: 'Continue with Google' })).toBeInTheDocument();
});

test('the prompt moves focus to its heading, so the change is announced', async () => {
  mockApi({
    '/me': jsonResponse(200, { ...LEARNER, consents_required: ['terms'] }),
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
  });
  renderWithProviders(<App />, { route: '/library' });

  const heading = await screen.findByRole('heading', { name: 'We updated our Terms of Service' });

  expect(heading).toHaveFocus();
});

test('a learner who has not accepted can still reach settings to export or delete', async () => {
  mockApi({
    '/me': jsonResponse(200, { ...LEARNER, consents_required: ['terms'] }),
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
    '/me/exports/latest': jsonResponse(200, { export: null }),
    '/me/consents': jsonResponse(200, { current: VERSIONS, consents: [] }),
  });
  const { router } = renderWithProviders(<App />, { route: '/library' });

  await screen.findByRole('heading', { name: 'We updated our Terms of Service' });
  fireEvent.click(screen.getByRole('link', { name: 'download your data or delete your account' }));

  expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe('/settings');
});

test('on a practice session the prompt waits until the server refuses a request', async () => {
  const fetchMock = mockApi({
    '/me': jsonResponse(200, { ...LEARNER, consents_required: ['terms'] }),
    '/auth/consent-versions': jsonResponse(200, VERSIONS),
    '/sessions/s1': problem(404, 'session_not_found', 'No such session.'),
    '/sessions/s2': problem(403, 'consent_required', 'Accept the updated terms.', {
      consents_required: ['terms'],
    }),
  });
  const { router } = renderWithProviders(<App />, { route: '/sessions/s1' });

  // An open practice page is not swapped out under the learner (a Blind listen).
  await vi.waitFor(() =>
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/sessions/s1')).toBe(true),
  );
  expect(screen.queryByRole('heading', { name: /We updated our/ })).not.toBeInTheDocument();

  await router.navigate('/sessions/s2');

  expect(
    await screen.findByRole('heading', { name: 'We updated our Terms of Service' }),
  ).toBeInTheDocument();
});
