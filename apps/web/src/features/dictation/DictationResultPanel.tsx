import { ApiError } from '../../api/client';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useDictationResult } from './api';
import { DictationDiff } from './DictationDiff';

/**
 * The learner's Dictation result on the session page (FR-DI-5). A submission made before
 * the transcript is ready waits, and the diff replaces the message when `dictation.scored`
 * arrives on the event stream (guards.tsx), without a reload.
 */
export function DictationResultPanel({ sessionId }: { sessionId: string }) {
  const result = useDictationResult(sessionId);
  if (result.isError) {
    if (result.error instanceof ApiError && result.error.code === 'attempt_not_found') return null;
    return <ErrorPanel error={result.error} onRetry={() => void result.refetch()} />;
  }
  const view = result.data;
  if (!view || view.scoring_status === null) return null;
  return (
    <section
      aria-labelledby="dictation-result"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 id="dictation-result" className="font-display text-heading">
        Your Dictation
      </h2>
      {view.result ? (
        <DictationDiff result={view.result} />
      ) : (
        <p role="status" className="text-ink-muted">
          Scoring when the transcript is ready. The result will appear here.
        </p>
      )}
    </section>
  );
}
