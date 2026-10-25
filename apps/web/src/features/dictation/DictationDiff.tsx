import type { DiffItem, DictationResult } from './api';
import { formatAccuracy } from './accuracy';
import { buttonClass } from '../../components/button';

type Marked = Exclude<DiffItem['status'], 'correct' | 'not_scored'>;

/**
 * Each status is told apart by a word and a line style as well as a colour (NFR-USE-2,
 * WCAG 1.4.1): spelling slip dotted, missing dashed, wrong wavy, extra struck through.
 */
const MARKS: Record<Marked, { label: string; word: string; swatch: string }> = {
  spelling_slip: {
    label: 'Spelling slip',
    word: 'underline decoration-dotted decoration-2 underline-offset-4',
    swatch: 'border-dotted border-ink',
  },
  missing: {
    label: 'Missing',
    word: 'text-diff-missing underline decoration-dashed decoration-2 underline-offset-4',
    swatch: 'border-dashed border-diff-missing',
  },
  wrong: {
    label: 'Wrong',
    word: 'text-diff-wrong underline decoration-wavy decoration-2 underline-offset-4',
    swatch: 'border-diff-wrong',
  },
  extra: {
    label: 'Extra',
    word: 'text-ink-muted line-through decoration-2',
    swatch: 'border-ink-muted',
  },
};
const ORDER: Marked[] = ['spelling_slip', 'missing', 'wrong', 'extra'];

function typedHint(item: DiffItem): string | null {
  if (item.status === 'extra') return null;
  if (item.status === 'missing') return 'you typed nothing';
  if (item.status === 'correct' || item.status === 'not_scored') return null;
  return `you typed ${item.typed}`;
}

/**
 * The diff view (FR-DI-5; design E02): the accuracy, a count of each status and every word
 * of the passage in order, with the words that went wrong marked. The reference text is
 * shown here and nowhere before scoring (FR-DI-3).
 */
export function DictationDiff({
  result,
  onCorrect,
}: {
  result: DictationResult;
  onCorrect?: (item: DiffItem) => void;
}) {
  const { counts } = result;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="font-display text-heading">Accuracy</h2>
        <p className="font-display text-display text-accent">{formatAccuracy(result.accuracy)}</p>
      </div>
      <ul aria-label="Summary" className="flex flex-wrap gap-x-4 gap-y-1 text-body-s">
        <li>
          <b>{counts.correct}</b> correct
        </li>
        <li>
          <b>{counts.spelling_slip}</b> spelling {counts.spelling_slip === 1 ? 'slip' : 'slips'}
        </li>
        <li>
          <b>{counts.wrong}</b> wrong
        </li>
        <li>
          <b>{counts.missing}</b> missing
        </li>
        <li>
          <b>{counts.extra}</b> extra
        </li>
      </ul>
      <ul aria-label="Key" className="flex flex-wrap gap-x-4 gap-y-1 text-body-s text-ink-muted">
        {ORDER.map((status) => (
          <li key={status} className="flex items-center gap-2">
            <span aria-hidden className={`inline-block w-6 border-b-2 ${MARKS[status].swatch}`} />
            {MARKS[status].label}
          </li>
        ))}
      </ul>
      <ul
        aria-label="Word by word"
        className="flex flex-wrap gap-x-3 gap-y-4 rounded-md border border-line bg-surface-raised p-4 text-body-l"
      >
        {result.items.map((item, position) => (
          <li key={`${item.index ?? 'x'}-${position}`} className="flex flex-col">
            <DiffWord item={item} />
            {onCorrect && item.index !== null && (
              <button
                type="button"
                className={buttonClass('quiet')}
                aria-label={`Correct reference word ${item.word || '(removed word)'}`}
                onClick={() => onCorrect(item)}
              >
                Correct reference
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DiffWord({ item }: { item: DiffItem }) {
  if (item.status === 'correct' || item.status === 'not_scored') {
    return <span data-word>{item.word || '(removed word)'}</span>;
  }
  const mark = MARKS[item.status];
  const hint = typedHint(item);
  return (
    <>
      <span data-word className={mark.word}>
        {item.status === 'extra' ? item.typed : item.word}
      </span>
      <span className="text-label font-bold text-ink-muted">{mark.label}</span>
      {hint && <span className="text-body-s text-ink-muted">{hint}</span>}
    </>
  );
}
