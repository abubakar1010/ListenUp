import { QueryCache, QueryClient } from '@tanstack/react-query';

import { ApiError } from '../api/client';
import { ME_KEY } from '../auth/useMe';

const MAX_RETRIES = 2;

/** Retry network failures and server errors; a 4xx answer will not change on retry. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.problem.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // A session that expires mid-use signs the learner out everywhere at once:
      // the signed-in guard sees `null` and sends them to sign in.
      onError: (error, query) => {
        if (
          error instanceof ApiError &&
          error.code === 'not_signed_in' &&
          query.queryKey[0] !== ME_KEY[0]
        ) {
          queryClient.setQueryData(ME_KEY, null);
        }
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000 },
      mutations: { retry: false },
    },
  });
  return queryClient;
}
