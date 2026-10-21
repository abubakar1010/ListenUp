import {
  MutationCache,
  QueryCache,
  QueryClient,
  type MutationFunctionContext,
  type MutationOptions,
  type MutationState,
} from '@tanstack/react-query';

import { ApiError, type Me } from '../api/client';
import { noteConsentRefused } from '../auth/consentApi';
import { changeSession, SessionChangedError } from '../auth/session';
import { ME_KEY } from '../auth/useMe';

const MAX_RETRIES = 2;

/** Retry network failures and server errors; a 4xx answer will not change on retry. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.problem.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function createQueryClient(): QueryClient {
  let learnerId: string | null | undefined;
  let generation = 0;
  const mutationGenerations = new WeakMap<object, number>();

  function isCurrent(request: MutationFunctionContext): boolean {
    return request.meta !== undefined && mutationGenerations.get(request.meta) === generation;
  }

  function requireCurrent(request: MutationFunctionContext): void {
    if (!isCurrent(request)) {
      throw new SessionChangedError();
    }
  }

  class SessionMutationCache extends MutationCache {
    override build<Data, Error, Variables, Context>(
      client: QueryClient,
      options: MutationOptions<Data, Error, Variables, Context>,
      state?: MutationState<Data, Error, Variables, Context>,
    ) {
      // Each execution needs a distinct metadata identity, even when one hook
      // reuses its options. React Query retains it in MutationFunctionContext.
      const defaults = client.defaultMutationOptions(options);
      return super.build(client, { ...defaults, meta: { ...defaults.meta } }, state);
    }
  }

  type Options = NonNullable<Parameters<QueryClient['defaultMutationOptions']>[0]>;
  class SessionQueryClient extends QueryClient {
    override defaultMutationOptions<T extends Options>(options?: T): T {
      const defaults = super.defaultMutationOptions(options);
      if (options?._defaulted) return defaults;
      return {
        ...defaults,
        mutationFn: defaults.mutationFn
          ? (variables: unknown, request: MutationFunctionContext) => {
              requireCurrent(request);
              return defaults.mutationFn!(variables, request);
            }
          : undefined,
        onSuccess: async (
          data: unknown,
          variables: unknown,
          context: unknown,
          request: MutationFunctionContext,
        ) => {
          requireCurrent(request);
          const result = defaults.onSuccess?.(data, variables, context, request);
          // A valid login/reset/logout synchronously publishes its own session.
          // Permit that mutation to finish in the session it just established.
          if (defaults.meta?.changesSession && request.meta) {
            mutationGenerations.set(request.meta, generation);
          }
          await result;
          requireCurrent(request);
        },
        onError: (
          error: unknown,
          variables: unknown,
          context: unknown,
          request: MutationFunctionContext,
        ) => {
          if (isCurrent(request)) return defaults.onError?.(error, variables, context, request);
        },
        onSettled: async (
          data: unknown,
          error: unknown,
          variables: unknown,
          context: unknown,
          request: MutationFunctionContext,
        ) => {
          if (error === null) requireCurrent(request);
          if (isCurrent(request)) {
            await defaults.onSettled?.(data, error, variables, context, request);
            if (error === null) requireCurrent(request);
          }
        },
      } as T;
    }
  }

  const queryClient: QueryClient = new SessionQueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (
          error instanceof ApiError &&
          error.code === 'not_signed_in' &&
          queryClient.getQueryCache().get(query.queryHash) === query
        ) {
          changeSession(queryClient, null);
        }
        if (error instanceof ApiError && error.code === 'consent_required') {
          noteConsentRefused(queryClient);
        }
      },
    }),
    mutationCache: new SessionMutationCache({
      onMutate: (_variables, _mutation, request) => {
        mutationGenerations.set(request.meta!, generation);
      },
      onSuccess: (_data, _variables, _context, _mutation, request) => {
        requireCurrent(request);
      },
      onSettled: (_data, error, _variables, _context, _mutation, request) => {
        if (error === null) requireCurrent(request);
      },
      onError: (error, _variables, _context, _mutation, request) => {
        if (isCurrent(request) && error instanceof ApiError && error.code === 'not_signed_in') {
          changeSession(queryClient, null);
        }
        if (isCurrent(request) && error instanceof ApiError && error.code === 'consent_required') {
          noteConsentRefused(queryClient);
        }
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000 },
      mutations: { retry: false },
    },
  });
  queryClient.getQueryCache().subscribe((event) => {
    if (
      event.type !== 'updated' ||
      event.action.type !== 'success' ||
      event.query.queryKey[0] !== ME_KEY[0]
    ) {
      return;
    }
    const me = event.query.state.data as Me | null;
    const nextId = me?.id ?? null;
    if (nextId === learnerId) return;
    // The first /me result identifies the existing session rather than changing
    // it. Later transitions also fence pending writes, including A → null → A.
    if (learnerId !== undefined) generation += 1;
    learnerId = nextId;
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
    queryClient.getMutationCache().clear();
  });
  return queryClient;
}
