import { useId, useState } from 'react';

import { ApiError } from '../../api/client';
import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { describeError } from '../../components/describeError';
import { ErrorPanel } from '../../components/ErrorPanel';
import NotFoundPage from '../../app/NotFoundPage';
import {
  isNotAdmin,
  useJobsOverview,
  useRetryJob,
  type FailedJob,
  type LaneBacklog,
} from './adminApi';
import { formatWait } from './formatWait';

const PAGE_CLASS =
  'mx-auto flex w-full max-w-content flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12 xl:px-8';
const SECTION_CLASS =
  'flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6';
const CELL = 'border-b border-line px-3 py-2 text-left align-top';
const NUMBER = `${CELL} text-right tabular-nums`;

/** What each lane holds (System Design 4.1), highest priority first. */
const LANE_NAMES: Record<LaneBacklog['lane'], string> = {
  'speech-interactive': 'Speech feedback',
  intake: 'Intake',
  ai: 'AI grading',
  background: 'Background',
};

function formatTime(iso: string | null): string {
  if (iso === null) return 'Unknown';
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function retryProblem(error: unknown, jobId: number): string {
  if (error instanceof ApiError && error.code === 'job_already_queued') {
    return `Job ${jobId} was not queued again: the same work is already waiting. Retry it once that job has run.`;
  }
  if (error instanceof ApiError && error.code === 'job_not_found') {
    return `Job ${jobId} is no longer waiting for a retry; the list has been reloaded.`;
  }
  const view = describeError(error);
  return `Job ${jobId} was not retried. ${view.detail} ${view.nextStep}`;
}

function BacklogTable({ lanes }: { lanes: LaneBacklog[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-body-s">
        <caption className="sr-only">Jobs per lane, highest priority first</caption>
        <thead>
          <tr>
            <th scope="col" className={CELL}>
              Lane
            </th>
            <th scope="col" className={NUMBER}>
              Waiting
            </th>
            <th scope="col" className={NUMBER}>
              Scheduled
            </th>
            <th scope="col" className={NUMBER}>
              Running
            </th>
            <th scope="col" className={NUMBER}>
              Longest wait
            </th>
          </tr>
        </thead>
        <tbody>
          {lanes.map((lane) => (
            <tr key={lane.lane}>
              <th scope="row" className={`${CELL} font-normal`}>
                {LANE_NAMES[lane.lane]} <span className="text-ink-muted">({lane.lane})</span>
              </th>
              <td className={NUMBER}>{lane.waiting}</td>
              <td className={NUMBER}>{lane.scheduled}</td>
              <td className={NUMBER}>{lane.running}</td>
              <td className={NUMBER}>{formatWait(lane.oldest_wait_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FailedTable({
  jobs,
  onRetry,
  retrying,
}: {
  jobs: FailedJob[];
  onRetry: (job: FailedJob) => void;
  retrying: number | null;
}) {
  if (jobs.length === 0) return <p>No failed jobs.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-body-s">
        <caption className="sr-only">Failed jobs, newest first</caption>
        <thead>
          <tr>
            <th scope="col" className={CELL}>
              Job
            </th>
            <th scope="col" className={CELL}>
              Lane
            </th>
            <th scope="col" className={NUMBER}>
              Attempts
            </th>
            <th scope="col" className={CELL}>
              Failed
            </th>
            <th scope="col" className={CELL}>
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <th scope="row" className={`${CELL} font-normal`}>
                <code>{job.name}</code> <span className="text-ink-muted">#{job.id}</span>
              </th>
              <td className={CELL}>{job.lane}</td>
              <td className={NUMBER}>{job.attempts}</td>
              <td className={CELL}>{formatTime(job.failed_at)}</td>
              <td className={CELL}>
                <button
                  type="button"
                  className={buttonClass('secondary')}
                  disabled={retrying !== null}
                  onClick={() => onRetry(job)}
                  aria-label={`Retry job ${job.id}, ${job.name}`}
                >
                  {retrying === job.id ? 'Retrying…' : 'Retry'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Administrators' job view (`/admin/jobs`, #100): backlog per lane and failed jobs
 * with a retry. Shows job names and counts only, never learner data. Anyone else gets
 * the API's 404 and sees the ordinary "Page not found".
 */
export default function JobsPage() {
  usePageTitle('Jobs');
  const backlogId = useId();
  const failedId = useId();
  const overview = useJobsOverview();
  const retry = useRetryJob();
  const [outcome, setOutcome] = useState<{ text: string; failed: boolean } | null>(null);

  if (overview.isError && isNotAdmin(overview.error)) return <NotFoundPage />;

  function onRetry(job: FailedJob) {
    setOutcome(null);
    retry.mutate(job.id, {
      onSuccess: (queued) =>
        setOutcome({
          text: `Job ${job.id} was queued again as job ${queued.job_id}.`,
          failed: false,
        }),
      onError: (error) => setOutcome({ text: retryProblem(error, job.id), failed: true }),
    });
  }

  return (
    <main className={PAGE_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-title-compact md:text-title">Jobs</h1>
        <button
          type="button"
          className={buttonClass('secondary')}
          onClick={() => void overview.refetch()}
          disabled={overview.isFetching}
        >
          {overview.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Always in the page, so screen readers announce what a retry did. */}
      <div role="status" className="empty:hidden">
        {outcome && (
          <p className={outcome.failed ? 'font-bold text-danger' : undefined}>{outcome.text}</p>
        )}
      </div>

      {overview.isPending ? (
        <p role="status" className="text-ink-muted">
          Loading jobs…
        </p>
      ) : overview.isError ? (
        <ErrorPanel error={overview.error} onRetry={() => void overview.refetch()} />
      ) : (
        <>
          <section aria-labelledby={backlogId} className={SECTION_CLASS}>
            <h2 id={backlogId} className="font-display text-heading-compact md:text-heading">
              Backlog by lane
            </h2>
            <BacklogTable lanes={overview.data.lanes} />
          </section>
          <section aria-labelledby={failedId} className={SECTION_CLASS}>
            <h2 id={failedId} className="font-display text-heading-compact md:text-heading">
              Failed jobs
            </h2>
            <p className="text-ink-muted">
              Jobs that used up their attempts, newest first. A retry queues the job again with
              fresh attempts.
            </p>
            <FailedTable
              jobs={overview.data.failed}
              onRetry={onRetry}
              retrying={retry.isPending ? (retry.variables ?? null) : null}
            />
          </section>
        </>
      )}
    </main>
  );
}
