import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router';

import { ApiError } from '../../api/client';
import type { LiveEvent } from '../../events/useLiveEvents';
import { contentKey, fetchContent, type ContentDetail } from './useContent';

/** One notice about a clip that finished processing while the learner was elsewhere. */
export interface ClipNotice {
  /** The clip the event was about. */
  contentId: string;
  text: string;
  link: { to: string; label: string };
}

/** At most this many notices show at once; older ones make way. */
const MAX_NOTICES = 3;

export function clipPage(contentId: string): string {
  return `/contents/${encodeURIComponent(contentId)}`;
}

function quoted(title: string): string {
  return `“${title}”`;
}

export function noticeFor(item: ContentDetail): ClipNotice | null {
  if (item.status === 'playable') {
    return {
      contentId: item.id,
      text: `${quoted(item.title)} is ready to practise.`,
      link: { to: clipPage(item.id), label: 'Open the clip' },
    };
  }
  if (item.status === 'failed') {
    return {
      contentId: item.id,
      text: `${quoted(item.title)} could not be prepared.`,
      link: { to: clipPage(item.id), label: 'See why' },
    };
  }
  return null;
}

export function noticeForError(contentId: string, error: unknown): ClipNotice | null {
  if (!(error instanceof ApiError) || error.code !== 'duplicate_upload') return null;
  const existingId = String(error.problem.existing_content_id ?? '');
  if (!existingId) return null;
  const title = String(error.problem.existing_title ?? 'this clip');
  return {
    contentId,
    text: `You already have ${quoted(title)}, so the copy you just added was not kept.`,
    link: { to: clipPage(existingId), label: 'Open it' },
  };
}

export interface ClipNoticesState {
  notices: ClipNotice[];
  onEvent: (event: LiveEvent) => void;
  dismiss: (contentId: string) => void;
}

/**
 * Turns `content.ready` events into notices (FR-CI-5, #40): a clip is ready, could not be
 * prepared, or was a copy of one the learner has. Nothing is shown for the clip whose own
 * page is open, since that page says it already.
 */
export function useClipNotices(): ClipNoticesState {
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const pathRef = useRef(pathname);
  useEffect(() => {
    pathRef.current = pathname;
  });
  const [notices, setNotices] = useState<ClipNotice[]>([]);

  const onEvent = useCallback(
    (event: LiveEvent) => {
      if (event.type !== 'content.ready') return;
      const contentId = event.resourceId;
      if (pathRef.current === clipPage(contentId)) return;
      queryClient
        .fetchQuery({
          queryKey: contentKey(contentId),
          queryFn: () => fetchContent(contentId),
          staleTime: 0,
          retry: false,
        })
        .then(noticeFor, (error: unknown) => noticeForError(contentId, error))
        .then((notice) => {
          if (!notice || pathRef.current === clipPage(contentId)) return;
          setNotices((current) =>
            [...current.filter((n) => n.contentId !== contentId), notice].slice(-MAX_NOTICES),
          );
        })
        .catch(() => undefined);
    },
    [queryClient],
  );

  const dismiss = useCallback((contentId: string) => {
    setNotices((current) => current.filter((n) => n.contentId !== contentId));
  }, []);

  return { notices, onEvent, dismiss };
}
