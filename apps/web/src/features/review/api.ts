import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import { SESSIONS_KEY } from '../session/api';

export type TranscriptReview = components['schemas']['TranscriptReview'];
export type TranscriptLine = components['schemas']['TranscriptLine'];
export const REVIEW_KEY = [...SESSIONS_KEY, 'transcript'] as const;
export const transcriptKey = (id: string) => [...REVIEW_KEY, id] as const;

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
