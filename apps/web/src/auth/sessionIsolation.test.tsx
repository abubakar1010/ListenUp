import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { App } from '../App';
import { ApiError, type Me } from '../api/client';
import { createQueryClient } from '../app/queryClient';
import { jsonResponse, LEARNER, problem } from '../test-utils';
import { ME_KEY } from './useMe';

const OTHER_LEARNER: Me = { ...LEARNER, id: '2', email: 'other@example.com' };
const PRIVATE_KEYS = [
  ['library', 'contents'],
  ['sessions', 'a-session'],
  ['exports', 'latest'],
];
const clients: ReturnType<typeof createQueryClient>[] = [];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function makeClient(me: Me | null) {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  client.setQueryData(ME_KEY, me);
  clients.push(client);
  return client;
}

function renderApp(client: ReturnType<typeof createQueryClient>, route: string) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function expectPrivateDataGone(client: ReturnType<typeof createQueryClient>) {
  for (const key of PRIVATE_KEYS) expect(client.getQueryData(key)).toBeUndefined();
}

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  for (const client of clients.splice(0)) client.clear();
});

test('an account replacement removes A clip notices and reconnects live events for B', async () => {
  const streams: Source[] = [];
  class Source {
    static CLOSED = 2;
    readyState = 1;
    closed = false;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    listeners = new Map<string, (message: MessageEvent<string>) => void>();
    constructor() {
      streams.push(this);
    }
    addEventListener(type: string, listener: (message: MessageEvent<string>) => void) {
      this.listeners.set(type, listener);
    }
    close() {
      this.closed = true;
      this.readyState = Source.CLOSED;
    }
  }
  vi.stubGlobal('EventSource', Source);
  const client = makeClient(LEARNER);
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input) === '/api/v1/contents/a-clip') {
      return jsonResponse(200, { id: 'a-clip', title: 'A private recording', status: 'playable' });
    }
    return jsonResponse(200, { items: [], next_cursor: null });
  });
  renderApp(client, '/library');
  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
  await waitFor(() => expect(streams).toHaveLength(1));
  act(() =>
    streams[0].listeners.get('content.ready')?.(
      new MessageEvent('content.ready', { data: JSON.stringify({ resource_id: 'a-clip' }) }),
    ),
  );
  expect(await screen.findByText('“A private recording” is ready to practise.')).toBeVisible();

  act(() => client.setQueryData(ME_KEY, OTHER_LEARNER));
  await waitFor(() => {
    expect(
      screen.queryByText('“A private recording” is ready to practise.'),
    ).not.toBeInTheDocument();
    expect(streams[0].closed).toBe(true);
    expect(streams).toHaveLength(2);
  });
});

test('expiry removes A data from the app while B library responses are pending', async () => {
  const client = makeClient(LEARNER);
  const clipA = {
    id: 'a-clip',
    title: 'A private recording',
    source: 'upload',
    status: 'playable',
    duration_ms: 30_000,
    created_at: '2026-10-03T09:00:00Z',
    last_session_status: null,
  };
  const clipB = { ...clipA, id: 'b-clip', title: 'B private recording' };
  client.setQueryData(PRIVATE_KEYS[0], {
    pages: [{ items: [clipA], next_cursor: null }],
    pageParams: [null],
  });
  client.setQueryData(PRIVATE_KEYS[1], { title: 'A private session' });
  client.setQueryData(PRIVATE_KEYS[2], { export: { id: 'a-private-export' } });
  let signedIn: 'a' | 'b' | null = 'a';
  const libraryB = deferred<Response>();
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input);
    if (path === '/api/v1/auth/login') {
      signedIn = 'b';
      return jsonResponse(200, OTHER_LEARNER);
    }
    if (path === '/api/v1/library/contents') {
      if (signedIn === null) return problem(401, 'not_signed_in', 'Sign in to continue.');
      if (signedIn === 'b') return libraryB.promise;
      return jsonResponse(200, { items: [clipA], next_cursor: null });
    }
    return jsonResponse(200, { items: [], next_cursor: null });
  });
  renderApp(client, '/library');
  expect(await screen.findByText(clipA.title)).toBeVisible();

  signedIn = null;
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['library'] });
  });
  expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  expectPrivateDataGone(client);
  expect(screen.queryByText(clipA.title)).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: OTHER_LEARNER.email } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a good password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
  expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
  expectPrivateDataGone(client);
  expect(screen.queryByText(clipA.title)).not.toBeInTheDocument();

  await act(async () => libraryB.resolve(jsonResponse(200, { items: [clipB], next_cursor: null })));
  expect(await screen.findByText(clipB.title)).toBeVisible();
  expect(screen.queryByText(clipA.title)).not.toBeInTheDocument();
});

test.each(['success', 'expired'] as const)(
  'sign-in as B ignores an older me request resolving with %s',
  async (outcome) => {
    const client = makeClient(null);
    const oldMe = deferred<Me>();
    const library = deferred<Response>();
    const oldResult = client
      .fetchQuery({ queryKey: ME_KEY, staleTime: 0, queryFn: () => oldMe.promise })
      .catch(() => undefined);
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      if (String(input) === '/api/v1/auth/login') return jsonResponse(200, OTHER_LEARNER);
      if (String(input) === '/api/v1/library/contents') return library.promise;
      return jsonResponse(200, { items: [], next_cursor: null });
    });
    renderApp(client, '/sign-in');
    fireEvent.change(await screen.findByLabelText('Email'), {
      target: { value: OTHER_LEARNER.email },
    });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a good password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();

    await act(async () => {
      if (outcome === 'success') oldMe.resolve(LEARNER);
      else {
        oldMe.reject(
          new ApiError({
            type: '/problems/not_signed_in',
            title: '',
            status: 401,
            code: 'not_signed_in',
            detail: 'Sign in to continue.',
          }),
        );
      }
      await oldResult;
    });

    expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
    expectPrivateDataGone(client);
    expect(screen.getByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument();
    await act(async () => library.resolve(jsonResponse(200, { items: [], next_cursor: null })));
  },
);

test('a completed password reset clears private data and cannot be undone by an old me response', async () => {
  const client = makeClient(LEARNER);
  for (const key of PRIVATE_KEYS) client.setQueryData(key, { title: 'A private data' });
  const oldMe = deferred<Me>();
  const oldResult = client
    .fetchQuery({ queryKey: ME_KEY, staleTime: 0, queryFn: () => oldMe.promise })
    .catch(() => undefined);
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(204));
  renderApp(client, '/reset-password#token=reset-token');
  fireEvent.change(await screen.findByLabelText('New password'), {
    target: { value: 'a new good password' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
  expect(await screen.findByRole('status')).toHaveTextContent('signed out everywhere');
  expectPrivateDataGone(client);

  await act(async () => {
    oldMe.resolve(LEARNER);
    await oldResult;
  });
  expect(client.getQueryData(ME_KEY)).toBeNull();
});

test('a failed password reset retains the signed-in learner and their cached data', async () => {
  const client = makeClient(LEARNER);
  for (const key of PRIVATE_KEYS) client.setQueryData(key, { title: 'A private data' });
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    problem(400, 'invalid_reset_link', 'This reset link has expired.'),
  );
  renderApp(client, '/reset-password#token=expired');
  fireEvent.change(await screen.findByLabelText('New password'), {
    target: { value: 'a new good password' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('expired'));

  expect(client.getQueryData(ME_KEY)).toEqual(LEARNER);
  for (const key of PRIVATE_KEYS)
    expect(client.getQueryData(key)).toEqual({ title: 'A private data' });
});

test('an older password reset cannot sign B out and explains the account change', async () => {
  const client = makeClient(LEARNER);
  const started = deferred<void>();
  const response = deferred<Response>();
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
    started.resolve();
    return response.promise;
  });
  renderApp(client, '/reset-password#token=a-reset-token');
  fireEvent.change(await screen.findByLabelText('New password'), {
    target: { value: 'a new good password' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
  await started.promise;
  act(() => client.setQueryData(ME_KEY, OTHER_LEARNER));
  await act(async () => response.resolve(jsonResponse(204)));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/account changed/i));

  expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
  expect(screen.queryByText(/signed out everywhere/)).not.toBeInTheDocument();
});
