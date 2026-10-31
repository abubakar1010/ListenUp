import { useState } from 'react';
import { Link } from 'react-router';

import { buttonClass, buttonProps } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { progressText, useDeleteSession, useSessions, type Session } from './api';
import { STEP_NAMES } from './plan';
import { formatClock } from './time';
import { BusyButton } from '../../components/BusyButton';

/**
 * The learner's plans, most recently active first, with where each one stands. Shows
 * nothing until the learner has started a plan. A plan can be deleted after
 * confirmation (FR-SH-17); its clip stays.
 */
export function SessionsSection() {
  const sessions = useSessions();
  const deletion = useDeleteSession();
  const [selected, setSelected] = useState<Session | null>(null);
  const [notice, setNotice] = useState('');
  const items = sessions.data?.pages.flatMap((page) => page.items) ?? [];

  function confirmDelete() {
    if (selected)
      deletion.mutate(selected.id, {
        onSuccess: () => {
          setSelected(null);
          setNotice('Plan deleted. Its recordings, marks and cards are being removed.');
        },
      });
  }

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
  if (items.length === 0) return notice ? <p role="status">{notice}</p> : null;
  // Plans come newest activity first: only the latest unfinished one gets the primary
  // Resume, so the page keeps one primary action (#197).
  const leadId = items.find((session) => session.status === 'active')?.id;

  return (
    <section aria-labelledby="library-plans" className="flex flex-col gap-3">
      <h2 id="library-plans" className="font-display text-heading-compact md:text-heading">
        Your plans
      </h2>
      {notice && <p role="status">{notice}</p>}
      {selected && (
        <ConfirmDialog
          title={`Delete this plan on ${selected.content_title}?`}
          confirmLabel="Delete plan"
          cancelLabel="Keep plan"
          onConfirm={confirmDelete}
          onCancel={() => setSelected(null)}
          busy={deletion.isPending}
          busyLabel="Deleting plan…"
          footer={
            deletion.isError ? (
              <ErrorPanel error={deletion.error} onRetry={confirmDelete} />
            ) : undefined
          }
        >
          <p>
            This permanently removes the plan&apos;s recordings, marks and cards, and its progress.
            The clip stays in your library. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
      <ul className="flex flex-col gap-3">
        {items.map((session) => (
          <SessionRow
            key={session.id}
            session={session}
            lead={session.id === leadId}
            onDelete={() => {
              deletion.reset();
              setSelected(session);
            }}
          />
        ))}
      </ul>
      {sessions.isFetchNextPageError && (
        <ErrorPanel error={sessions.error} onRetry={() => void sessions.fetchNextPage()} />
      )}
      {sessions.hasNextPage && (
        <BusyButton
          className={buttonClass('secondary', 'self-start')}
          onClick={() => void sessions.fetchNextPage()}
          busy={sessions.isFetchingNextPage}
        >
          {sessions.isFetchingNextPage ? 'Loading more plans…' : 'More plans'}
        </BusyButton>
      )}
    </section>
  );
}

function SessionRow({
  session,
  lead,
  onDelete,
}: {
  session: Session;
  lead: boolean;
  onDelete: () => void;
}) {
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
      <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
        <button type="button" onClick={onDelete} className={buttonClass('secondary')}>
          Delete plan <span className="sr-only">{session.content_title}</span>
        </button>
        <Link to={`/sessions/${session.id}`} {...buttonProps(lead ? 'primary' : 'secondary')}>
          {active ? 'Resume' : 'View'} <span className="sr-only">{session.content_title}</span>
        </Link>
      </div>
    </li>
  );
}
