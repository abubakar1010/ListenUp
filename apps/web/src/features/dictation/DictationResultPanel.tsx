import { ApiError } from '../../api/client';
import { useState } from 'react';
import { ErrorPanel } from '../../components/ErrorPanel';
import { formatAccuracy } from './accuracy';
import { type DiffItem, type OpenMarkList, useDictationResult } from './api';
import { CorrectionDialog } from './CorrectionDialog';
import { DictationDiff } from './DictationDiff';
import { DictationMarks } from './DictationMarks';

/**
 * The learner's Dictation result on the session page (FR-DI-5). A submission made before
 * the transcript is ready waits, and the diff replaces the message when `dictation.scored`
 * arrives on the event stream (guards.tsx), without a reload. Its missed and wrong words
 * can then be added to the mark list (#55).
 */
export function DictationResultPanel({
  sessionId,
  markList,
}: {
  sessionId: string;
  markList?: OpenMarkList;
}) {
  const result = useDictationResult(sessionId);
  const [editing, setEditing] = useState<DiffItem | null>(null);
  // A score that arrives while the panel waits is announced (UX-04, UX-22); one already
  // there when the panel opens is simply shown.
  const [waited, setWaited] = useState(false);
  const view = result.data;
  if (view && !view.result && view.scoring_status !== null && !waited) setWaited(true);
  if (result.isError) {
    if (result.error instanceof ApiError && result.error.code === 'attempt_not_found') return null;
    return <ErrorPanel error={result.error} onRetry={() => void result.refetch()} />;
  }
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
        <>
          <DictationDiff result={view.result} onCorrect={setEditing} />
          <DictationMarks attemptId={view.id} items={view.result.items} markList={markList} />
          {editing && (
            <CorrectionDialog
              sessionId={sessionId}
              attemptId={view.id}
              item={editing}
              onClose={() => setEditing(null)}
            />
          )}
        </>
      ) : view.scoring_status === 'scoring_unavailable' ? (
        <p role="status" className="text-ink-muted">
          We could not score this Dictation because the transcript is unavailable. Your text is
          saved, and the plan can go on. If the transcript is made later, the result appears here.
        </p>
      ) : (
        <p role="status" className="text-ink-muted">
          Scoring when the transcript is ready. The result will appear here.
        </p>
      )}
      <p role="status" className="sr-only" data-testid="dictation-announcement">
        {waited && view.result
          ? `Your Dictation is scored: ${formatAccuracy(view.result.accuracy)}.`
          : ''}
      </p>
    </section>
  );
}
