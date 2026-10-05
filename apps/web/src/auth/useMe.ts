import { useQuery } from '@tanstack/react-query';

import { api, ApiError, type Me } from '../api/client';

export const ME_KEY = ['me'] as const;

/** The signed-in learner, or null when nobody is signed in. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<Me | null> => {
      try {
        return await api<Me>('/me');
      } catch (error) {
        if (error instanceof ApiError && error.code === 'not_signed_in') return null;
        throw error;
      }
    },
    retry: false,
  });
}
