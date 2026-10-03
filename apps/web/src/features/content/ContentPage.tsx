import { Link, useParams } from 'react-router';

import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { formatDuration } from '../../components/formatDuration';
import { AlertIcon, BackIcon } from '../../components/icons';
import { ApiError } from '../../api/client';
import { stageSentence } from './intakeStatus';
import { isProcessing, useContent, type ContentDetail } from './useContent';

const PAGE_CLASS =
  'mx-auto flex w-full max-w-content flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12 xl:px-8';

/**
 * One clip (`/contents/:contentId`, FR-CI-5): whether it is still being prepared, ready
 * to play or failed with the reason, and a basic player once it is ready. The player
 * streams from storage with range requests, so it starts on the first bytes and seeks
 * without downloading the whole file (NFR-PERF-1, NFR-PERF-4).
 */
export default function ContentPage() {
  const { contentId = '' } = useParams();
  const content = useContent(contentId);
  usePageTitle(content.data?.title ?? 'Clip');

  return (
    <main className={PAGE_CLASS}>
      <Link to="/library" className={buttonClass('quiet', 'self-start')}>
        <BackIcon />
        Library
      </Link>
      {content.isPending && (
        <p role="status" className="text-ink-muted">
          Loading the clip…
        </p>
      )}
      {content.isError && !content.data && (
        <ClipError error={content.error} retry={content.refetch} />
      )}
      {content.data && <Clip item={content.data} />}
    </main>
  );
}

/**
 * Why the clip cannot be shown. A copy of a clip the learner already has was removed by
 * the server (ADR 0022); say so and link to the clip they have (NFR-USE-3, #39).
 */
function ClipError({ error, retry }: { error: unknown; retry: () => unknown }) {
  if (error instanceof ApiError && error.code === 'duplicate_upload') {
    const existingId = String(error.problem.existing_content_id ?? '');
    const existingTitle = String(error.problem.existing_title ?? 'your clip');
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-2 rounded-md border-2 border-line-strong bg-surface-raised p-4"
      >
        <h1 className="font-display text-heading">You already have this clip</h1>
        <p>{error.problem.detail}</p>
        {existingId && (
          <Link
            to={`/contents/${encodeURIComponent(existingId)}`}
            className={buttonClass('primary', 'mt-2')}
          >
            Open {existingTitle}
          </Link>
        )}
      </div>
    );
  }
  return <ErrorPanel error={error} onRetry={() => void retry()} headingLevel={1} />;
}

function Clip({ item }: { item: ContentDetail }) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-title-compact break-words md:text-title">{item.title}</h1>
        <p className="text-body-s text-ink-muted">
          {item.source === 'youtube' ? 'YouTube' : 'Upload'}
          {item.duration_ms !== null && (
            <>
              {' · '}
              <span className="font-mono">{formatDuration(item.duration_ms)}</span>
            </>
          )}
        </p>
      </div>
      <section aria-labelledby="clip-player" className="flex flex-col gap-3">
        <h2 id="clip-player" className="font-display text-heading-compact md:text-heading">
          Player
        </h2>
        <ClipStatus item={item} />
        {item.status === 'playable' && item.media_url && (
          <Player item={item} url={item.media_url} />
        )}
      </section>
    </>
  );
}

/** Announced politely, so a screen reader hears when processing finishes. */
function ClipStatus({ item }: { item: ContentDetail }) {
  if (item.status === 'failed') {
    return (
      <div
        role="alert"
        className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 rounded-md border-2 border-warning bg-surface-raised p-4"
      >
        <span className="pt-0.5 text-warning">
          <AlertIcon className="size-6" />
        </span>
        <div className="flex flex-col items-start gap-2">
          <p className="font-bold">This clip could not be prepared</p>
          <p>{item.error_detail ?? 'Something went wrong while we prepared this clip.'}</p>
          <Link to="/library/add" className={buttonClass('secondary', 'mt-2')}>
            Add another file
          </Link>
        </div>
      </div>
    );
  }
  return (
    <p role="status" className="flex items-center gap-2">
      {isProcessing(item.status) && (
        <span
          aria-hidden="true"
          className="size-4 animate-spin rounded-full border-2 border-line border-t-accent"
        />
      )}
      {statusText(item)}
    </p>
  );
}

function statusText(item: ContentDetail): string {
  switch (item.status) {
    case 'playable':
      return 'Ready to play.';
    case 'expired':
      return 'This clip needs downloading again before you can play it.';
    default:
      return stageSentence(item);
  }
}

function Player({ item, url }: { item: ContentDetail; url: string }) {
  const label = `Play ${item.title}`;
  if (item.has_video) {
    return (
      <video
        controls
        preload="metadata"
        playsInline
        src={url}
        aria-label={label}
        className="w-full max-w-[640px] rounded-md bg-ink"
      />
    );
  }
  return <audio controls preload="metadata" src={url} aria-label={label} className="w-full" />;
}
