import { MutationObserver } from '@tanstack/react-query';

import { ApiError, type Me } from '../api/client';
import { ME_KEY } from '../auth/useMe';
import { LEARNER } from '../test-utils';
import { createQueryClient } from './queryClient';

const OTHER_LEARNER: Me = { ...LEARNER, id: '2', email: 'other@example.com' };
const PRIVATE_KEYS = [
  ['library', 'contents'],
  ['sessions', 'a-session'],
  ['exports', 'latest'],
];
const clients: ReturnType<typeof createQueryClient>[] = [];

function clientWithLearner() {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
  client.setQueryData(ME_KEY, LEARNER);
  for (const key of PRIVATE_KEYS) client.setQueryData(key, { title: 'A private data' });
  clients.push(client);
  return client;
}

function refused(code = 'not_signed_in', status = 401) {
  return new ApiError({ type: '/problems/auth', title: '', detail: code, code, status });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function expectPrivateDataGone(client: ReturnType<typeof createQueryClient>) {
  for (const key of PRIVATE_KEYS) expect(client.getQueryData(key)).toBeUndefined();
}

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

test('a private query reporting session expiry immediately removes cached learner data', async () => {
  const client = clientWithLearner();
  await expect(
    client.fetchQuery({ queryKey: ['uploads', 'usage'], queryFn: () => Promise.reject(refused()) }),
  ).rejects.toMatchObject({ code: 'not_signed_in' });

  expect(client.getQueryData(ME_KEY)).toBeNull();
  expectPrivateDataGone(client);
});

test('a mutation reporting session expiry signs out and removes private data', async () => {
  const client = clientWithLearner();
  const mutation = client.getMutationCache().build(client, {
    mutationFn: () => Promise.reject(refused()),
  });
  await expect(mutation.execute(undefined)).rejects.toMatchObject({ code: 'not_signed_in' });

  expect(client.getQueryData(ME_KEY)).toBeNull();
  expectPrivateDataGone(client);
});

test('a me refresh returning signed out removes all previously cached private data', async () => {
  const client = clientWithLearner();
  await client.fetchQuery({ queryKey: ME_KEY, staleTime: 0, queryFn: () => Promise.resolve(null) });

  expectPrivateDataGone(client);
});

test('replacing learner A with learner B removes A data before B requests complete', () => {
  const client = clientWithLearner();
  client.setQueryData(ME_KEY, OTHER_LEARNER);

  expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
  expectPrivateDataGone(client);
});

test('a successful me refresh for the same learner preserves their private cache', async () => {
  const client = clientWithLearner();
  await client.fetchQuery({
    queryKey: ME_KEY,
    staleTime: 0,
    queryFn: () => Promise.resolve({ ...LEARNER, display_name: 'Updated name' }),
  });

  for (const key of PRIVATE_KEYS)
    expect(client.getQueryData(key)).toEqual({ title: 'A private data' });
});

test.each([
  ['network', new TypeError('Network unavailable')],
  ['server', refused('unavailable', 503)],
  ['forbidden', refused('forbidden', 403)],
  ['invalid credentials', refused('invalid_credentials', 401)],
])('%s errors do not erase a valid account or its data', async (_name, error) => {
  const client = clientWithLearner();
  await expect(
    client.fetchQuery({ queryKey: ['request'], queryFn: () => Promise.reject(error) }),
  ).rejects.toBe(error);
  const mutation = client.getMutationCache().build(client, {
    mutationFn: () => Promise.reject(error),
  });
  await expect(mutation.execute(undefined)).rejects.toBe(error);

  expect(client.getQueryData(ME_KEY)).toEqual(LEARNER);
  for (const key of PRIVATE_KEYS)
    expect(client.getQueryData(key)).toEqual({ title: 'A private data' });
});

test.each(['success', 'expired'] as const)(
  'a late private query %s from A cannot change B cache or authentication',
  async (outcome) => {
    const client = clientWithLearner();
    const response = deferred<{ title: string }>();
    const oldResult = client
      .fetchQuery({ queryKey: ['library', 'late'], queryFn: () => response.promise })
      .catch(() => undefined);
    client.setQueryData(ME_KEY, null);
    client.setQueryData(ME_KEY, OTHER_LEARNER);
    client.setQueryData(PRIVATE_KEYS[0], { title: 'B private data' });

    if (outcome === 'success') response.resolve({ title: 'A late private data' });
    else response.reject(refused());
    await oldResult;

    expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
    expect(client.getQueryData(['library', 'late'])).toBeUndefined();
    expect(client.getQueryData(PRIVATE_KEYS[0])).toEqual({ title: 'B private data' });
  },
);

test.each(['success', 'expired'] as const)(
  'a late mutation %s from A cannot restore A data or sign B out',
  async (outcome) => {
    const client = clientWithLearner();
    const response = deferred<{ title: string }>();
    const started = deferred<void>();
    const onSuccess = vi.fn((data: { title: string }) =>
      client.setQueryData(PRIVATE_KEYS[2], data),
    );
    const mutation = client.getMutationCache().build(client, {
      mutationFn: () => {
        started.resolve();
        return response.promise;
      },
      onSuccess,
    });
    const oldResult = mutation.execute(undefined).catch(() => undefined);
    await started.promise;
    client.setQueryData(ME_KEY, null);
    client.setQueryData(ME_KEY, OTHER_LEARNER);
    client.setQueryData(PRIVATE_KEYS[2], { title: 'B private export' });

    if (outcome === 'success') response.resolve({ title: 'A private export' });
    else response.reject(refused());
    await oldResult;

    expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
    expect(client.getQueryData(PRIVATE_KEYS[2])).toEqual({ title: 'B private export' });
    expect(onSuccess).not.toHaveBeenCalled();
  },
);

test.each(['mutation first', 'account first'] as const)(
  'concurrent mutation and account responses (%s) cannot retain A private data',
  async (order) => {
    const client = clientWithLearner();
    const response = deferred<{ title: string }>();
    const account = deferred<Me>();
    const started = deferred<void>();
    const mutation = client.getMutationCache().build(client, {
      mutationFn: () => {
        started.resolve();
        return response.promise;
      },
      onSuccess: (data) => {
        client.setQueryData(PRIVATE_KEYS[2], data);
      },
    });
    const oldResult = mutation.execute(undefined).catch(() => undefined);
    await started.promise;
    const newAccount = client.fetchQuery({
      queryKey: ME_KEY,
      staleTime: 0,
      queryFn: () => account.promise,
    });
    if (order === 'mutation first') {
      response.resolve({ title: 'A private export' });
      account.resolve(OTHER_LEARNER);
    } else {
      account.resolve(OTHER_LEARNER);
      response.resolve({ title: 'A private export' });
    }
    await Promise.all([oldResult, newAccount]);
    expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
    expectPrivateDataGone(client);
  },
);

test('reused mutation options cannot give an old execution the new account generation', async () => {
  const client = clientWithLearner();
  const response = deferred<{ title: string }>();
  const started = deferred<void>();
  const options = {
    meta: { purpose: 'export' },
    mutationFn: (owner: string) => {
      if (owner === 'a') {
        started.resolve();
        return response.promise;
      }
      return Promise.resolve({ title: 'B private export' });
    },
    onSuccess: (data: { title: string }) => {
      client.setQueryData(PRIVATE_KEYS[2], data);
    },
  };
  const old = client
    .getMutationCache()
    .build(client, options)
    .execute('a')
    .catch(() => undefined);
  await started.promise;
  client.setQueryData(ME_KEY, OTHER_LEARNER);
  await client.getMutationCache().build(client, options).execute('b');
  response.resolve({ title: 'A private export' });
  await old;

  expect(client.getQueryData(PRIVATE_KEYS[2])).toEqual({ title: 'B private export' });
  expect(options.meta).toEqual({ purpose: 'export' });
});

test('a mutation settling across an account change cannot deliver its old success callback', async () => {
  const client = clientWithLearner();
  const settling = deferred<void>();
  const release = deferred<void>();
  const observer = new MutationObserver(client, {
    mutationFn: () => Promise.resolve({ title: 'A private export' }),
    onSettled: async () => {
      settling.resolve();
      await release.promise;
    },
  });
  const delivered = vi.fn();
  const unsubscribe = observer.subscribe(() => {});
  const oldResult = observer.mutate(undefined, { onSuccess: delivered }).catch((error) => error);
  await settling.promise;
  client.setQueryData(ME_KEY, OTHER_LEARNER);
  client.setQueryData(PRIVATE_KEYS[2], { title: 'B private export' });
  release.resolve();
  const result = await oldResult;
  unsubscribe();

  expect(result).toBeInstanceOf(Error);
  expect(delivered).not.toHaveBeenCalled();
  expect(client.getQueryData(PRIVATE_KEYS[2])).toEqual({ title: 'B private export' });
});

test('old mutation error and settled callbacks cannot operate on the new account', async () => {
  const client = clientWithLearner();
  const response = deferred<void>();
  const started = deferred<void>();
  const onError = vi.fn();
  const onSettled = vi.fn();
  const mutation = client.getMutationCache().build(client, {
    mutationFn: () => {
      started.resolve();
      return response.promise;
    },
    onError,
    onSettled,
  });
  const old = mutation.execute(undefined).catch(() => undefined);
  await started.promise;
  client.setQueryData(ME_KEY, OTHER_LEARNER);
  response.reject(refused('draft_conflict', 409));
  await old;
  expect(onError).not.toHaveBeenCalled();
  expect(onSettled).not.toHaveBeenCalled();
  expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
});

test('a mutation waiting for setup cannot send its request after the account changes', async () => {
  const client = clientWithLearner();
  const preparing = deferred<void>();
  const release = deferred<void>();
  const send = vi.fn(() => Promise.resolve({ title: 'A private export' }));
  const mutation = client.getMutationCache().build(client, {
    onMutate: async () => {
      preparing.resolve();
      await release.promise;
    },
    mutationFn: send,
  });
  const oldResult = mutation.execute(undefined).catch((error) => error);
  await preparing.promise;
  client.setQueryData(ME_KEY, OTHER_LEARNER);
  release.resolve();

  expect(await oldResult).toBeInstanceOf(Error);
  expect(send).not.toHaveBeenCalled();
  expect(client.getQueryData(ME_KEY)).toEqual(OTHER_LEARNER);
});

test('registered mutation defaults retain their request metadata', async () => {
  const client = clientWithLearner();
  client.setMutationDefaults(['write'], {
    meta: { purpose: 'registered default' },
    mutationFn: (_variables, request) => Promise.resolve(request.meta?.purpose),
  });
  const mutation = client.getMutationCache().build(client, { mutationKey: ['write'] });
  expect(await mutation.execute(undefined)).toBe('registered default');
});
