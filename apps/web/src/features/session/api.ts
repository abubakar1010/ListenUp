import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { LIBRARY_KEY } from '../library/useLibrary';

export type Session = components['schemas']['Session'];
export type SessionList = components['schemas']['SessionList'];
export type StartSession = components['schemas']['StartSession'];

/** Everything about sessions; invalidate it when a session starts or changes. */
export const SESSIONS_KEY = ['sessions'] as const;
export const SESSIONS_LIST_KEY = [...SESSIONS_KEY, 'list'] as const;
export const sessionKey = (id: string) => [...SESSIONS_KEY, 'detail', id] as const;

/** One session with its plan. */
export function useSession(id: string) {
  return useQuery({
    queryKey: sessionKey(id),
    queryFn: () => api<Session>(`/sessions/${encodeURIComponent(id)}`),
  });
}

/** The learner's sessions, most recently active first, 20 per page. */
export function useSessions() {
  return useInfiniteQuery({
    queryKey: SESSIONS_LIST_KEY,
    queryFn: ({ pageParam }) =>
      api<SessionList>(
        pageParam ? `/sessions?cursor=${encodeURIComponent(pageParam)}` : '/sessions',
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}

/**
 * Start a plan. The caller passes one Idempotency-Key per plan it means to start, so a
 * retry after a lost answer returns the same session instead of a second one.
 */
export function useStartSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: StartSession; key: string }) =>
      api<Session>('/sessions', { method: 'POST', body, headers: { 'Idempotency-Key': key } }),
    onSuccess: (session) => {
      queryClient.setQueryData(sessionKey(session.id), session);
      void queryClient.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
      void queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
  });
}

/** "Step 2 of 5", or "Complete" once the plan is finished. */
export function progressText(session: Session): string {
  if (session.status === 'completed') return `All ${session.step_count} steps finished`;
  if (session.open_position === null) return `Stopped · ${session.step_count} steps`;
  return `Step ${session.open_position} of ${session.step_count}`;
}
