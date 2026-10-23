import { type ReactNode, useMemo, useState } from 'react';

import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import type { Range } from '../review/selection';
import { type DiffItem, type OpenMarkList, useAddDictationMarks, useDictationMarks } from './api';
import { candidateRuns, isAdded, isRunAdded, rangesToAddAll, type Run } from './marks';

const quoted = (text: string) => `“${text}”`;

/**
 * Add missed or wrong words of the diff to the mark list (#55, FR-DI-6): a word or a run
 * of words in one action, or all of them. The marks wait in Transcript for the learner to
 * confirm (FR-TR-3), and words already marked show as added. Every action is a native
 * button, so Tab reaches it and Enter or Space adds; an added button stays focusable and
 * says so (aria-disabled), so focus never drops to the page. Beside an open transcript
 * it shares the transcript's `markList` instead of reading its own.
 */
export function DictationMarks({
  attemptId,
  items,
  markList,
}: {
  attemptId: string;
  items: DiffItem[];
  markList?: OpenMarkList;
}) {
  const runs = useMemo(() => candidateRuns(items), [items]);
  const marks = useDictationMarks(attemptId, !markList);
  const add = useAddDictationMarks(attemptId, markList?.take);
  const [announcement, setAnnouncement] = useState('');

  if (runs.length === 0) return null;
  if (!markList && marks.isError)
    return <ErrorPanel error={marks.error} onRetry={() => void marks.refetch()} />;
  const known = markList?.marks ?? marks.data;
  if (!known) return null;

  const remaining = rangesToAddAll(runs, known);
  const submit = (ranges: Range[], done: string) => {
    if (ranges.length === 0 || add.isPending) return;
    add.mutate(ranges, { onSuccess: () => setAnnouncement(done) });
  };
  const addRange = (range: Range, phrase: string) => {
    if (!isAdded(known, range)) submit([range], `Added ${quoted(phrase)} to your marks.`);
  };
  // A run follows the add-all rule: words already added alone keep their own marks.
  const addRun = (run: Run, phrase: string) =>
    submit(rangesToAddAll([run], known), `Added ${quoted(phrase)} to your marks.`);

  return (
    <section aria-labelledby="dictation-marks" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="dictation-marks" className="font-display text-title">
          Add to your marks
        </h3>
        <button
          type="button"
          className={buttonClass('secondary')}
          aria-disabled={remaining.length === 0 || add.isPending}
          onClick={() =>
            submit(
              remaining,
              `Added ${remaining.length} ${remaining.length === 1 ? 'mark' : 'marks'} to your marks.`,
            )
          }
        >
          {remaining.length === 0 ? 'All added' : 'Add all'}
        </button>
      </div>
      <p className="text-body-s text-ink-muted">
        Missed and wrong words wait in Transcript, where you confirm them for your cards and Shadow.
      </p>
      <ul aria-label="Missed and wrong words" className="flex flex-col gap-2">
        {runs.map((run) => {
          const phrase = run.words.map((w) => w.word).join(' ');
          return (
            <li
              key={`${run.word_from}-${run.word_to}`}
              aria-label={quoted(phrase)}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-line p-3"
            >
              <span className="font-bold">{quoted(phrase)}</span>
              <span className="text-body-s text-ink-muted">
                {run.words.map((w) => (w.status === 'missing' ? 'Missing' : 'Wrong')).join(', ')}
              </span>
              <AddButton
                phrase={phrase}
                added={isRunAdded(known, run)}
                busy={add.isPending}
                onAdd={() => addRun(run, phrase)}
              >
                {isRunAdded(known, run) ? 'Added' : 'Add'}
              </AddButton>
              {run.words.length > 1 && (
                <span className="flex flex-wrap items-center gap-2 text-body-s">
                  <span className="text-ink-muted">Or one word:</span>
                  {run.words.map((w) => {
                    const range = { word_from: w.index!, word_to: w.index! };
                    return (
                      <AddButton
                        key={w.index}
                        phrase={w.word}
                        added={isAdded(known, range)}
                        busy={add.isPending}
                        onAdd={() => addRange(range, w.word)}
                      >
                        {w.word}
                        {isAdded(known, range) && <span aria-hidden> ✓</span>}
                      </AddButton>
                    );
                  })}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {add.isError && (
        <ErrorPanel error={add.error} onRetry={() => add.variables && add.mutate(add.variables)} />
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

function AddButton({
  phrase,
  added,
  busy,
  onAdd,
  children,
}: {
  phrase: string;
  added: boolean;
  busy: boolean;
  onAdd: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={buttonClass('quiet')}
      aria-label={added ? `${quoted(phrase)} added to marks` : `Add ${quoted(phrase)} to marks`}
      aria-disabled={added || busy}
      onClick={onAdd}
    >
      {children}
    </button>
  );
}
