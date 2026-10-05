import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { LIBRARY_KEY } from '../library/useLibrary';
import type { Entry, Step } from './plan';

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

function useSessionWrite<Vars>(
  session: Session,
  write: (vars: Vars, version: number) => Promise<Session>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => write(vars, session.version),
    onSuccess: (updated) => {
      queryClient.setQueryData(sessionKey(updated.id), updated);
      void queryClient.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
      void queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
    // Refused (locked, changed elsewhere): load the session as the server has it.
    onError: () => queryClient.invalidateQueries({ queryKey: sessionKey(session.id) }),
  });
}

/** Change Blind, Dictation or both until Transcript opens (FR-PL-5). */
export function useChangeEntry(session: Session) {
  return useSessionWrite(session, (entry: Entry, version) =>
    api<Session>(`/sessions/${session.id}/entry`, {
      method: 'PATCH',
      body: { entry, version },
    }),
  );
}

/** Skip Card or Shadow after the learner confirmed (FR-PL-7). */
export function useSkipStep(session: Session) {
  return useSessionWrite(session, (step: Step, version) =>
    api<Session>(`/sessions/${session.id}/steps/${step}/skip`, {
      method: 'POST',
      body: { confirmed: true, version },
    }),
  );
}

/** "Step 2 of 5", or "Complete" once the plan is finished. */
export function progressText(session: Session): string {
  if (session.status === 'completed') return `All ${session.step_count} steps finished`;
  if (session.open_position === null) return `Stopped · ${session.step_count} steps`;
  return `Step ${session.open_position} of ${session.step_count}`;
}
