import { useEffect, type ReactNode } from 'react';
import { Link } from 'react-router';

import { HEADER_CLASS } from '../../app/headerClass';
import { BackIcon, LockIcon } from '../../components/icons';

export interface PracticeLayoutProps {
  /** The page's h1 for screen readers, for example "Dictation: Why cities plant street trees". */
  heading: string;
  /** The clip's title, shown in the header. */
  clipTitle: string;
  /** A short line under the title, for example the passage's time range. */
  clipMeta?: ReactNode;
  /** The back link ("Plan"). Pass null to hide it, as Blind playback does (UX-19). */
  back?: { to: string; label: string } | null;
  /** Save status, for example "Draft saved 10:51". */
  status?: ReactNode;
  /** Header actions, for example the "Keys" button. */
  actions?: ReactNode;
  /** Slot: step progress for the plan. */
  progress: ReactNode;
  /** Slot: the player, owned by the mode's control policy in media/. */
  player: ReactNode;
  /** Slot: the mode's rule in one line, for example "No pausing. Listen once." (UI-2). */
  rule: ReactNode;
  /** Accessible name of the work area, usually the mode's task. */
  workLabel?: string;
  /** Slot: the mode's work area. */
  children: ReactNode;
  /** Slot: side panel (marks, gist, feedback); beside the work area from 1024 px, below it before. */
  aside?: ReactNode;
}

/**
 * The practice screen, the same in every mode (UI-1): header, then step progress,
 * the player, the one-line rule and the work area, with an optional side panel.
 * Content is at most 1120 px wide; the header stays at the top while scrolling,
 * and the page's scroll padding keeps focused controls out from under it
 * (WCAG 2.4.11).
 */
export function PracticeLayout({
  heading,
  clipTitle,
  clipMeta,
  back = null,
  status,
  actions,
  progress,
  player,
  rule,
  workLabel = 'Practice',
  children,
  aside,
}: PracticeLayoutProps) {
  useStickyHeaderScrollPadding();
  return (
    <div className="min-h-dvh">
      <header className={`${HEADER_CLASS} sticky top-0 z-10 pl-2 md:pl-4`}>
        {back && (
          <Link
            to={back.to}
            className="inline-flex min-h-11 flex-none items-center gap-1 rounded-md py-2 pr-2 pl-1 font-bold text-accent no-underline"
          >
            <BackIcon />
            {back.label}
          </Link>
        )}
        <div className="flex min-w-0 flex-col">
          <p className="truncate font-bold">{clipTitle}</p>
          {clipMeta && (
            <p className="truncate font-mono text-label font-medium tracking-normal text-ink-muted">
              {clipMeta}
            </p>
          )}
        </div>
        <span className="flex-1" />
        {status && (
          <span className="hidden items-center gap-1 text-body-s whitespace-nowrap text-ink-muted sm:inline-flex">
            {status}
          </span>
        )}
        {actions}
      </header>
      <main className="mx-auto flex w-full max-w-content flex-col gap-4 px-4 pt-4 pb-8 md:gap-6 md:px-6 md:pt-8 md:pb-12 xl:px-8">
        <h1 className="sr-only">{heading}</h1>
        <section aria-label="Plan progress" data-slot="progress">
          {progress}
        </section>
        <section aria-label="Player" data-slot="player">
          {player}
        </section>
        <p
          data-slot="rule"
          className="flex items-center gap-2 rounded-sm bg-surface-sunken px-3 py-2 text-body-s font-bold"
        >
          <LockIcon className="size-4 flex-none" />
          <span>{rule}</span>
        </p>
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-8">
          <section aria-label={workLabel} data-slot="work" className="flex min-w-0 flex-col gap-4">
            {children}
          </section>
          {aside && (
            <aside aria-label="Side panel" data-slot="aside" className="flex flex-col gap-4">
              {aside}
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}

/** While the screen is shown, scrolling to a focused control leaves room for the sticky header. */
function useStickyHeaderScrollPadding() {
  useEffect(() => {
    const root = document.documentElement;
    const before = root.style.scrollPaddingTop;
    root.style.scrollPaddingTop = '4.5rem';
    return () => {
      root.style.scrollPaddingTop = before;
    };
  }, []);
}
