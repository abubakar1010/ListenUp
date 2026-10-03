import { useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

import { api, ApiError } from '../../api/client';
import {
  LIBRARY_CONTENTS_KEY,
  LIBRARY_KEY,
  type LibraryItem,
  type LibraryPage,
} from '../library/useLibrary';

const MAX_PAGES = 20;

/**
 * One clip of the learner's library: from the library already loaded, else from its
 * pages. Kept under the library key, so a `content.ready` event refreshes it.
 *
 * There is no endpoint for one content item yet; switch to it once it exists.
 */
export function useClip(contentId: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: [...LIBRARY_KEY, 'clip', contentId],
    queryFn: async (): Promise<LibraryItem> => {
      const loaded = queryClient.getQueryData<InfiniteData<LibraryPage>>(LIBRARY_CONTENTS_KEY);
      const known = loaded?.pages.flatMap((page) => page.items).find((i) => i.id === contentId);
      // A clip still being prepared may be ready by now, so only a playable one is reused.
      if (known?.status === 'playable') return known;
      let cursor: string | null = null;
      for (let n = 0; n < MAX_PAGES; n += 1) {
        const query: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
        const page: LibraryPage = await api<LibraryPage>(`/library/contents?limit=50${query}`);
        const found = page.items.find((item) => item.id === contentId);
        if (found) return found;
        if (!page.next_cursor) break;
        cursor = page.next_cursor;
      }
      throw new ApiError({
        type: '/problems/content_not_found',
        title: 'Not Found',
        status: 404,
        detail: 'There is no such clip in your library.',
        code: 'content_not_found',
      });
    },
  });
}
