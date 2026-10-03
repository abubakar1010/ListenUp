import { Link, useLocation } from 'react-router';

import { buttonClass } from '../../components/button';
import { clipPage, type ClipNoticesState } from './useClipNotices';

/**
 * Where the notices appear: a polite live region at the bottom of the screen, so a screen
 * reader hears them without losing its place, and focus never moves (NFR-USE-2). They stay
 * until dismissed or followed, with no time limit. During practice they wait until the
 * learner leaves the session, so nothing talks over the audio of a Blind or Shadow step.
 */
function noticeTextId(contentId: string): string {
  return `clip-notice-${contentId}`;
}

export function ClipNotices({ notices }: { notices: ClipNoticesState }) {
  const { pathname } = useLocation();
  const practising = pathname.startsWith('/sessions/');
  const visible = practising
    ? []
    : notices.notices.filter((notice) => pathname !== clipPage(notice.contentId));

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-20 flex flex-col items-center gap-2 p-4 sm:items-end"
    >
      {visible.map((notice) => (
        <div
          key={notice.contentId}
          className="pointer-events-auto flex w-full max-w-sm flex-col gap-2 rounded-md border border-line-strong bg-surface-raised p-4 shadow-lg"
        >
          <p id={noticeTextId(notice.contentId)} className="break-words">
            {notice.text}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={notice.link.to}
              className={buttonClass('secondary')}
              onClick={() => notices.dismiss(notice.contentId)}
            >
              {notice.link.label}
            </Link>
            <button
              type="button"
              aria-describedby={noticeTextId(notice.contentId)}
              className={buttonClass('quiet')}
              onClick={() => notices.dismiss(notice.contentId)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
