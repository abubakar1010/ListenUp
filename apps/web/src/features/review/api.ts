import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { LIBRARY_KEY } from '../library/useLibrary';
import { SESSIONS_KEY, SESSIONS_LIST_KEY, sessionKey } from '../session/api';
import type { MarkTransport, SavedMark } from './markSync';

export type TranscriptReview = components['schemas']['TranscriptReview'];
export type TranscriptLine = components['schemas']['TranscriptLine'];
export const REVIEW_KEY = [...SESSIONS_KEY, 'transcript'] as const;
export const transcriptKey = (id: string) => [...REVIEW_KEY, id] as const;

export function useFinishTranscript(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<void>(`/sessions/${encodeURIComponent(id)}/transcript/complete`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `transcript-${id}` },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: sessionKey(id) });
      void client.invalidateQueries({ queryKey: SESSIONS_LIST_KEY });
      void client.invalidateQueries({ queryKey: LIBRARY_KEY });
    },
    // A lost answer may already have opened Card; reload the authoritative plan.
    onError: () => client.invalidateQueries({ queryKey: sessionKey(id) }),
  });
}

export function useTranscript(id: string) {
  return useQuery({
    queryKey: transcriptKey(id),
    queryFn: () => api<TranscriptReview>(`/sessions/${encodeURIComponent(id)}/transcript`),
    retry: false,
    // Poll pending work too: readiness may precede subscription or EventSource.
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.code === 'transcript_not_ready'
        ? 5000
        : false,
  });
}

export type MarkList = components['schemas']['MarkList'];
export const marksKey = (id: string) => [...SESSIONS_KEY, 'marks', id] as const;

/**
 * The session's saved marks, read each time Transcript opens (#58, NFR-REL-1).
 * `MarkSync` takes the list once and then owns it, so a copy kept in the query cache would
 * go stale as marks are made: it is dropped as soon as the screen closes (`gcTime: 0`),
 * and coming back to Transcript reads the list again.
 */
export function useMarks(id: string) {
  return useQuery({
    queryKey: marksKey(id),
    queryFn: () => api<MarkList>(`/sessions/${encodeURIComponent(id)}/marks`),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });
}

/** The marks API as `MarkSync` sends to it. */
export function markTransport(sessionId: string): MarkTransport {
  const path = `/sessions/${encodeURIComponent(sessionId)}/marks`;
  return {
    create: (mark) => api<SavedMark>(path, { method: 'POST', body: mark }),
    setNote: (id, note) =>
      api<SavedMark>(`${path}/${encodeURIComponent(id)}`, { method: 'PATCH', body: { note } }),
    confirm: (id) =>
      api<SavedMark>(`${path}/${encodeURIComponent(id)}/status`, {
        method: 'PUT',
        body: { status: 'confirmed' },
      }),
    remove: (id) => api<void>(`${path}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    list: async () => (await api<MarkList>(path)).marks,
  };
}
