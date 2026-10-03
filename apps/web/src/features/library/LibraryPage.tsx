import { Link } from 'react-router';

import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { AlertIcon } from '../../components/icons';
import { ACCEPTED_NAMES } from './files';
import { useLibraryContents, type LibraryItem } from './useLibrary';

const STEPS = [
  {
    label: '1 · Listen first',
    name: 'Blind or Dictation',
    text: "Hear the clip before you see any text, so you find what you really can't catch.",
  },
  {
    label: '2 · Find the gaps',
    name: 'Transcript',
    text: "Read along and mark every place where the sound didn't match the words.",
  },
  {
    label: '3 · Train them',
    name: 'Card and Shadow',
    text: 'Keep two sounds, then speak with the speaker three times.',
  },
];

const PAGE_CLASS =
  'mx-auto flex w-full max-w-content flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12 xl:px-8';

/** The learner's library (`/library`, FR-LB-1): their clips, newest first. */
export default function LibraryPage() {
  usePageTitle('Library');
  const contents = useLibraryContents();
  const items = contents.data?.pages.flatMap((page) => page.items) ?? [];

  if (contents.isPending) {
    return (
      <main className={PAGE_CLASS}>
        <h1 className="font-display text-title-compact md:text-title">Library</h1>
        <p role="status" className="text-ink-muted">
          Loading your clips…
        </p>
      </main>
    );
  }

  if (contents.isError && items.length === 0) {
    return (
      <main className={PAGE_CLASS}>
        <h1 className="font-display text-title-compact md:text-title">Library</h1>
        <ErrorPanel error={contents.error} onRetry={() => void contents.refetch()} />
      </main>
    );
  }

  if (items.length === 0) return <EmptyLibrary />;

  return (
    <main className={PAGE_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-title-compact md:text-title">Library</h1>
        <Link to="/library/add" className={buttonClass('primary')}>
          Add a clip
        </Link>
      </div>
      <section aria-labelledby="library-clips" className="flex flex-col gap-3">
        <h2 id="library-clips" className="font-display text-heading-compact md:text-heading">
          Clips
        </h2>
        <ul className="flex flex-col gap-3">
          {items.map((item) => (
            <ClipRow key={item.id} item={item} />
          ))}
        </ul>
        {contents.isFetchNextPageError && (
          <ErrorPanel error={contents.error} onRetry={() => void contents.fetchNextPage()} />
        )}
        {contents.hasNextPage && (
          <button
            type="button"
            className={buttonClass('secondary', 'self-start')}
            onClick={() => void contents.fetchNextPage()}
            disabled={contents.isFetchingNextPage}
          >
            {contents.isFetchingNextPage ? 'Loading more clips…' : 'Load more'}
          </button>
        )}
      </section>
    </main>
  );
}

function EmptyLibrary() {
  return (
    <main className={PAGE_CLASS}>
      <section
        aria-labelledby="library-empty"
        className="grid justify-items-center gap-4 rounded-md border-2 border-dashed border-line-strong bg-surface-raised px-4 py-8 text-center md:gap-6 md:py-16"
      >
        <h1 id="library-empty" className="font-display text-display-compact md:text-display">
          Add your first clip
        </h1>
        <p className="max-w-[68ch]">
          Pick something you want to understand: a talk, a podcast, a scene from a series. Two to
          three minutes of it is enough for one plan.
        </p>
        <Link to="/library/add" className={buttonClass('primary')}>
          Upload a file
        </Link>
        <p className="text-body-s text-ink-muted">{ACCEPTED_NAMES}, up to 500 MB per file.</p>
      </section>
      <section aria-labelledby="library-how" className="flex flex-col gap-4">
        <h2 id="library-how" className="font-display text-heading-compact md:text-heading">
          How a plan works
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map((step) => (
            <li
              key={step.label}
              className="flex flex-col gap-1 rounded-md border border-line bg-surface-raised p-4"
            >
              <span className="text-label text-ink-muted uppercase">{step.label}</span>
              <b>{step.name}</b>
              <span className="text-body-s text-ink-muted">{step.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

const SOURCE_LABEL: Record<LibraryItem['source'], string> = {
  upload: 'Upload',
  youtube: 'YouTube',
};

const SESSION_LABEL: Record<NonNullable<LibraryItem['last_session_status']>, string> = {
  active: 'In progress',
  completed: 'Completed',
  abandoned: 'Stopped',
};

function ClipRow({ item }: { item: LibraryItem }) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <b className="break-words">{item.title}</b>
        <span className="text-body-s text-ink-muted">
          {SOURCE_LABEL[item.source]}
          {item.duration_ms !== null && (
            <>
              {' · '}
              <span className="font-mono">{formatDuration(item.duration_ms)}</span>
            </>
          )}
          {' · Added '}
          {formatDate(item.created_at)}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={item.status} />
        {item.last_session_status && (
          <span className={BADGE}>Last session: {SESSION_LABEL[item.last_session_status]}</span>
        )}
      </div>
    </li>
  );
}

const BADGE =
  'inline-flex min-h-7 items-center gap-1.5 rounded-full border border-line px-3 text-body-s';

function StatusBadge({ status }: { status: LibraryItem['status'] }) {
  if (status === 'playable') {
    return <span className={`${BADGE} border-success text-success`}>Ready</span>;
  }
  if (status === 'failed') {
    return (
      <span className={`${BADGE} border-warning text-warning`}>
        <AlertIcon className="size-4" />
        Could not be processed
      </span>
    );
  }
  if (status === 'expired') {
    return <span className={`${BADGE} text-ink-muted`}>Needs downloading again</span>;
  }
  return (
    <span className={BADGE}>
      <span
        aria-hidden="true"
        className="size-3 animate-spin rounded-full border-2 border-line border-t-accent"
      />
      {status === 'downloading' ? 'Downloading' : 'Processing'}
    </span>
  );
}

function formatDuration(ms: number): string {
  const total = Math.round(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${String(minutes).padStart(2, '0')}:${seconds}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
