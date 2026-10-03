import { Link } from 'react-router';

import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { progressText, useSessions, type Session } from './api';
import { STEP_NAMES } from './plan';
import { formatClock } from './time';

/**
 * The learner's plans, most recently active first, with where each one stands. Shows
 * nothing until the learner has started a plan.
 */
export function SessionsSection() {
  const sessions = useSessions();
  const items = sessions.data?.pages.flatMap((page) => page.items) ?? [];

  if (sessions.isError && items.length === 0) {
    return (
      <section aria-labelledby="library-plans" className="flex flex-col gap-3">
        <h2 id="library-plans" className="font-display text-heading-compact md:text-heading">
          Your plans
        </h2>
        <ErrorPanel error={sessions.error} onRetry={() => void sessions.refetch()} />
      </section>
    );
  }
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="library-plans" className="flex flex-col gap-3">
      <h2 id="library-plans" className="font-display text-heading-compact md:text-heading">
        Your plans
      </h2>
      <ul className="flex flex-col gap-3">
        {items.map((session) => (
          <SessionRow key={session.id} session={session} />
        ))}
      </ul>
      {sessions.isFetchNextPageError && (
        <ErrorPanel error={sessions.error} onRetry={() => void sessions.fetchNextPage()} />
      )}
      {sessions.hasNextPage && (
        <button
          type="button"
          className={buttonClass('secondary', 'self-start')}
          onClick={() => void sessions.fetchNextPage()}
          disabled={sessions.isFetchingNextPage}
        >
          {sessions.isFetchingNextPage ? 'Loading more plans…' : 'More plans'}
        </button>
      )}
    </section>
  );
}

function SessionRow({ session }: { session: Session }) {
  const active = session.status === 'active';
  return (
    <li className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <b className="break-words">{session.content_title}</b>
        <span className="text-body-s text-ink-muted">
          <span className="font-mono">
            {formatClock(session.passage.start_ms)} to {formatClock(session.passage.end_ms)}
          </span>
          {' · '}
          {progressText(session)}
          {session.open_step && ` · ${STEP_NAMES[session.open_step]}`}
        </span>
      </div>
      <Link
        to={`/sessions/${session.id}`}
        className={buttonClass(active ? 'primary' : 'secondary', 'self-start sm:self-auto')}
      >
        {active ? 'Resume' : 'View'} <span className="sr-only">{session.content_title}</span>
      </Link>
    </li>
  );
}
