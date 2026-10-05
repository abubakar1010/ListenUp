import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { useLocation } from 'react-router';

import { App } from './App';
import {
  jsonResponse,
  LEARNER,
  mockApi,
  problem,
  renderWithProviders,
  SIGNED_OUT,
} from './test-utils';
import { blindStepFixture } from './features/blind/fixtures';
import { sessionFixture } from './features/session/fixtures';

afterEach(() => vi.restoreAllMocks());

function CurrentUrl() {
  const location = useLocation();
  return <output data-testid="url">{`${location.pathname}${location.search}`}</output>;
}

function renderApp(route: string) {
  return renderWithProviders(
    <>
      <App />
      <CurrentUrl />
    </>,
    { route },
  );
}

const url = () => screen.getByTestId('url').textContent;

test('shows the product name and offers sign-in when nobody is signed in', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderApp('/');

  expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'ListenUp' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
    'href',
    '/register',
  );
  expect(document.title).toBe('Sign in · ListenUp');
});

test('a signed-in learner starts in the library with their account in the header', async () => {
  mockApi({ '/me': () => jsonResponse(200, LEARNER) });
  renderApp('/');

  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
  expect(url()).toBe('/library');
  await waitFor(() => expect(document.title).toBe('Library · ListenUp'));
  expect(
    within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link'),
  ).toHaveAttribute('aria-current', 'page');
});

test('the account menu shows who is signed in and signs out', async () => {
  let signedIn = true;
  mockApi({
    '/me': () => (signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT()),
    '/health': () => jsonResponse(200, { status: 'ok' }),
    '/auth/logout': () => {
      signedIn = false;
      return new Response(null, { status: 204 });
    },
  });
  renderApp('/library');

  const account = await screen.findByRole('button', { name: 'Account' });
  expect(account).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(account);
  expect(account).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByText('learner@example.com')).toBeVisible();
  expect(screen.getByText(/Signed in as/)).toHaveTextContent('Signed in as learner@example.com');

  fireEvent.keyDown(document, { key: 'Escape' });
  expect(account).toHaveAttribute('aria-expanded', 'false');
  expect(account).toHaveFocus();

  fireEvent.click(account);
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

  expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
});

test('a signed-out learner who opens a session signs in and comes back to it', async () => {
  let signedIn = false;
  document.cookie = 'listenup_csrf=token-123';
  mockApi({
    '/me': () => (signedIn ? jsonResponse(200, LEARNER) : SIGNED_OUT()),
    '/auth/login': () => {
      signedIn = true;
      return jsonResponse(200, LEARNER);
    },
    '/sessions/abc-123': () => jsonResponse(200, sessionFixture({ id: 'abc-123' })),
    '/sessions/abc-123/blind': () => jsonResponse(200, blindStepFixture(null, 'abc-123')),
  });
  renderApp('/sessions/abc-123?step=transcript');

  expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
  expect(url()).toBe('/sign-in?next=%2Fsessions%2Fabc-123%3Fstep%3Dtranscript');

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'learner@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

  expect(
    await screen.findByRole('heading', {
      name: 'Blind: Why cities plant street trees',
      level: 1,
    }),
  ).toBeInTheDocument();
  expect(url()).toBe('/sessions/abc-123?step=transcript');
});

test('sign-in ignores a next address on another site', async () => {
  mockApi({ '/me': () => jsonResponse(200, LEARNER) });
  renderApp('/sign-in?next=//evil.example/steal');

  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
  expect(url()).toBe('/library');
});

test('the practice screen has its slots in order: progress, player, rule, work', async () => {
  mockApi({
    '/me': () => jsonResponse(200, LEARNER),
    '/sessions/abc-123': () => jsonResponse(200, sessionFixture({ id: 'abc-123' })),
    '/sessions/abc-123/blind': () => jsonResponse(200, blindStepFixture(null, 'abc-123')),
  });
  renderApp('/sessions/abc-123');

  await screen.findByRole('region', { name: 'Plan progress' });
  const main = screen.getByRole('main');
  const slots = [...main.querySelectorAll('[data-slot]')].map((el) => el.getAttribute('data-slot'));
  expect(slots).toEqual(['progress', 'player', 'rule', 'work']);
  expect(screen.getByRole('region', { name: 'Player' })).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Plan progress' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library');
});

test('when the account cannot be checked, the page says so and offers a retry', async () => {
  let calls = 0;
  mockApi({
    '/me': () => {
      calls += 1;
      return calls === 1
        ? problem(503, 'service_unavailable', 'The service is busy.')
        : jsonResponse(200, LEARNER);
    },
  });
  renderApp('/library');

  const alert = await screen.findByRole('alert');
  expect(within(alert).getByRole('heading', { level: 1 })).toHaveTextContent(
    'Something went wrong on our side',
  );
  expect(alert).toHaveTextContent('The service is busy.');
  expect(alert).toHaveTextContent('Try again in a moment.');

  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
});

test('an unknown address shows a not-found page with a way back', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderApp('/no-such-page');

  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Go to your library' })).toHaveAttribute('href', '/');
});

test('every page starts with a skip link to the content', async () => {
  mockApi({ '/me': () => jsonResponse(200, LEARNER) });
  renderApp('/library');

  const main = await screen.findByRole('main');
  const skip = screen.getByRole('link', { name: 'Skip to content' });
  expect(document.body.querySelector('a')).toBe(skip);

  fireEvent.click(skip);
  expect(main).toHaveFocus();
});

test('the forgotten-password page is linked from sign-in', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderApp('/sign-in');

  fireEvent.click(await screen.findByRole('link', { name: 'Forgot your password?' }));

  await waitFor(() => expect(url()).toBe('/forgot-password'));
  expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
});

test('a reset link opens even for a signed-in learner', async () => {
  mockApi({ '/me': () => jsonResponse(200, LEARNER) });
  renderApp('/reset-password');

  expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
  expect(url()).toBe('/reset-password');
});

test('switching between sign-in and register keeps where to return', async () => {
  mockApi({ '/me': SIGNED_OUT });
  renderApp('/sign-in?next=%2Fsessions%2Fabc');

  expect(await screen.findByRole('link', { name: 'Create an account' })).toHaveAttribute(
    'href',
    '/register?next=%2Fsessions%2Fabc',
  );
});

test('the account menu leads to the settings page with the data download', async () => {
  mockApi({
    '/me': () => jsonResponse(200, LEARNER),
    '/me/exports/latest': () => jsonResponse(200, { export: null }),
  });
  renderApp('/library');

  fireEvent.click(await screen.findByRole('button', { name: 'Account' }));
  fireEvent.click(screen.getByRole('link', { name: 'Settings' }));

  expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Download your data' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Account' })).toHaveAttribute('aria-expanded', 'false');
});
