import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type LibraryItem = components['schemas']['LibraryItem'];
export type LibraryPage = components['schemas']['LibraryPage'];
export type StorageUse = components['schemas']['StorageUse'];

/** Everything the library shows; invalidate it when an item is added or changes. */
export const LIBRARY_KEY = ['library'] as const;
export const LIBRARY_CONTENTS_KEY = [...LIBRARY_KEY, 'contents'] as const;
export const UPLOAD_USAGE_KEY = ['uploads', 'usage'] as const;

/** The learner's clips, newest first, one keyset page (20 items) at a time (FR-LB-1). */
export function useLibraryContents() {
  return useInfiniteQuery({
    queryKey: LIBRARY_CONTENTS_KEY,
    queryFn: ({ pageParam }) =>
      api<LibraryPage>(
        pageParam
          ? `/library/contents?cursor=${encodeURIComponent(pageParam)}`
          : '/library/contents',
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
}

/** How much of the 2 GB upload storage is used (D5). */
export function useUploadUsage() {
  return useQuery({
    queryKey: UPLOAD_USAGE_KEY,
    queryFn: () => api<StorageUse>('/uploads/usage'),
  });
}
