import { useQuery } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type ContentDetail = components['schemas']['ContentDetail'];

/** Every content item's query; refetch them all when live events may have been missed. */
export const CONTENTS_KEY = ['contents'] as const;

export function contentKey(contentId: string) {
  return [...CONTENTS_KEY, contentId] as const;
}

/** How often a clip still being prepared is checked when no live event arrives. */
export const PROCESSING_POLL_MS = 5000;

export function isProcessing(status: ContentDetail['status']): boolean {
  return status === 'pending' || status === 'downloading';
}

/**
 * One clip of the learner's library (`GET /contents/{id}`). While it is being prepared it
 * refreshes on the `content.ready` live event and, as a fallback, every few seconds.
 */
export function useContent(contentId: string) {
  return useQuery({
    queryKey: contentKey(contentId),
    queryFn: () => api<ContentDetail>(`/contents/${encodeURIComponent(contentId)}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && isProcessing(status) ? PROCESSING_POLL_MS : false;
    },
  });
}
