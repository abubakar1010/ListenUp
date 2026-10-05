import { useId } from 'react';

import { ApiError } from '../../api/client';
import { buttonClass } from '../../components/button';
import { describeError } from '../../components/describeError';
import { ErrorPanel } from '../../components/ErrorPanel';
import { formatSize } from '../library/files';
import { formatReset } from '../library/refusals';
import { isPreparing, useLatestExport, useRequestExport, type DataExport } from './exportApi';

function formatDate(iso: string): string {
  const date = new Date(iso);
  const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${day} at ${time}`;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What the latest export is doing, in a sentence or two. */
function statusText(found: DataExport | null): string {
  if (found === null) return 'You have not asked for a copy of your data yet.';
  switch (found.status) {
    case 'pending':
    case 'building':
      return 'We are preparing your download. This can take a few minutes; you can leave this page and come back.';
    case 'ready': {
      const size = found.archive_bytes === null ? '' : `${formatSize(found.archive_bytes)}, `;
      const files = plural(found.file_count ?? 0, 'media file', 'media files');
      const until = found.expires_at ? ` It is kept until ${formatDate(found.expires_at)}.` : '';
      return `Your download is ready (${size}${files} and your data as JSON).${until}`;
    }
    case 'failed':
      return 'We could not prepare your download. Ask for a new one; if it fails again, try later.';
    case 'expired':
      return 'Your last download has expired and its file was deleted. Ask for a new one.';
  }
}

function requestProblem(error: unknown): { title: string; detail: string } {
  if (error instanceof ApiError && error.code === 'rate_limited') {
    const when =
      error.retryAfterSeconds === null
        ? 'tomorrow'
        : formatReset(new Date(Date.now() + error.retryAfterSeconds * 1000).toISOString());
    return {
      title: 'You have asked for several downloads today',
      detail: `You can ask for a new one ${when}.`,
    };
  }
  if (error instanceof ApiError && error.code === 'export_in_progress') {
    return { title: 'A download is already being prepared', detail: error.problem.detail };
  }
  const view = describeError(error);
  return { title: view.title, detail: `${view.detail} ${view.nextStep}` };
}

/**
 * "Download your data" (NFR-SEC-5, #92): ask for a copy of everything the learner has
 * stored, see when it is ready, and download it. Self-contained, so it can sit on any
 * account or settings page.
 */
export function DataExportSection() {
  const headingId = useId();
  const latest = useLatestExport();
  const request = useRequestExport();
  const found = latest.data?.export ?? null;
  const preparing = found !== null && isPreparing(found.status);
  const problem = request.isError ? requestProblem(request.error) : null;

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 id={headingId} className="font-display text-heading-compact md:text-heading">
        Download your data
      </h2>
      <p>
        Get a copy of everything you have stored in ListenUp: your account, clips, practice sessions
        and attempts as a JSON file, together with the audio and video files you uploaded, in one
        ZIP file. Files of clips you added from YouTube are not included; their links, titles and
        your practice on them are.
      </p>

      {latest.isPending ? (
        <p role="status" className="text-ink-muted">
          Checking your downloads…
        </p>
      ) : latest.isError ? (
        <ErrorPanel error={latest.error} onRetry={() => void latest.refetch()} />
      ) : (
        <>
          <p role="status" className={preparing ? 'font-bold' : undefined}>
            {statusText(found)}
          </p>
          <div className="flex flex-wrap gap-3">
            {found?.download_url && (
              <a href={found.download_url} download className={buttonClass('primary')}>
                Download your data (ZIP)
              </a>
            )}
            <button
              type="button"
              onClick={() => request.mutate()}
              disabled={preparing || request.isPending}
              className={buttonClass(found?.download_url ? 'secondary' : 'primary')}
            >
              {request.isPending
                ? 'Asking…'
                : preparing
                  ? 'Preparing…'
                  : found === null
                    ? 'Prepare my download'
                    : 'Prepare a new download'}
            </button>
          </div>
          {problem && (
            <div role="alert" className="flex flex-col gap-1 text-body-s">
              <p className="font-bold text-danger">{problem.title}</p>
              <p>{problem.detail}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
