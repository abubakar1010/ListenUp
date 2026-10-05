import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { SESSIONS_KEY, SESSIONS_LIST_KEY, sessionKey } from '../session/api';
import { LIBRARY_KEY } from '../library/useLibrary';

export type BlindAttempt = components['schemas']['BlindAttempt'];
export type BlindStep = components['schemas']['BlindStep'];
export type StartedAttempt = components['schemas']['StartedAttempt'];
export type HeartbeatIn = components['schemas']['HeartbeatIn'];
export type HeartbeatOut = components['schemas']['HeartbeatOut'];
export type GistSubmitted = components['schemas']['GistSubmitted'];
export type VoidReason = components['schemas']['VoidReason'];
export type ClientVoidReason = components['schemas']['VoidIn']['reason'];

/** Under the sessions key, so anything that refreshes a session refreshes this too. */
export const blindKey = (sessionId: string) => [...SESSIONS_KEY, 'blind', sessionId] as const;
/** Every Blind step, for the `attempt.voided` event, which names only the attempt. */
export const BLIND_KEY = [...SESSIONS_KEY, 'blind'] as const;

/** The Blind step with its newest attempt, so a reloaded page knows where it stands. */
export function useBlindStep(sessionId: string) {
  return useQuery({
    queryKey: blindKey(sessionId),
    queryFn: () => api<BlindStep>(`/sessions/${encodeURIComponent(sessionId)}/blind`),
  });
}

export function startAttempt(sessionId: string): Promise<StartedAttempt> {
  return api<StartedAttempt>(`/sessions/${encodeURIComponent(sessionId)}/blind/attempts`, {
    method: 'POST',
  });
}

export function sendHeartbeat(attemptId: string, beat: HeartbeatIn): Promise<HeartbeatOut> {
  return api<HeartbeatOut>(`/blind/attempts/${attemptId}/heartbeat`, {
    method: 'POST',
    body: beat,
  });
}

/**
 * Report leaving, a reload or a seek. `keepalive` lets it reach the server while the
 * page unloads (the job `navigator.sendBeacon` does, but with the CSRF header).
 */
export function voidAttempt(
  attemptId: string,
  reason: ClientVoidReason,
  keepalive = false,
): Promise<BlindAttempt> {
  return api<BlindAttempt>(`/blind/attempts/${attemptId}/void`, {
    method: 'POST',
    body: { reason },
    keepalive,
  });
}

/**
 * Submit the gist. One Idempotency-Key per attempt, so a retry after a lost answer
 * returns the first answer instead of a refusal.
 */
export function useSubmitGist(sessionId: string, attemptId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<GistSubmitted>(`/blind/attempts/${attemptId}/gist`, {
        method: 'POST',
        body: { text },
        headers: { 'Idempotency-Key': `gist-${attemptId}` },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sessionKey(sessionId) });
      void queryClient.invalidateQueries({ queryKey: blindKey(sessionId) });
      void queryClient.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
      void queryClient.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
  });
}
