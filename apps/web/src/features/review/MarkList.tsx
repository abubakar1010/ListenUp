import { buttonClass } from '../../components/button';
import { formatClock } from '../session/time';
import type { LocalMark } from './markSync';

/** FR-TR-5: one audio-ordered list of the same local marks highlighted in the text. */
export function MarkList({
  marks,
  phraseOf,
  onPlay,
  onEdit,
  onRemove,
}: {
  marks: LocalMark[];
  phraseOf: (mark: LocalMark) => string;
  onPlay: (mark: LocalMark) => void;
  onEdit: (mark: LocalMark) => void;
  onRemove: (mark: LocalMark) => void;
}) {
  return (
    <section
      aria-label="Your marks"
      className="flex min-w-0 flex-col gap-3 rounded-md border border-line p-3"
    >
      <h3 className="font-bold">Your marks</h3>
      <p className="text-body-s">
        Enter plays a mark. E edits its note. Delete removes it; Undo brings it back.
      </p>
      {marks.length === 0 ? (
        <p>No marks yet. Choose a word to mark a sound you missed.</p>
      ) : (
        <ol aria-label="Your marks" className="flex flex-col gap-3">
          {marks.map((mark) => {
            const phrase = phraseOf(mark) || '(removed words)';
            return (
              <li key={mark.id} className="min-w-0 rounded-sm bg-surface-raised p-2">
                <button
                  type="button"
                  className={buttonClass(
                    'secondary',
                    'w-full text-left whitespace-normal [overflow-wrap:anywhere]',
                  )}
                  aria-label={`Play mark ${phrase} at ${formatClock(mark.at_ms)}`}
                  onClick={() => onPlay(mark)}
                  onKeyDown={(event) => {
                    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
                    if (event.key.toLowerCase() === 'e') {
                      event.preventDefault();
                      onEdit(mark);
                    } else if (event.key === 'Delete') {
                      event.preventDefault();
                      onRemove(mark);
                    }
                  }}
                >
                  {formatClock(mark.at_ms)} · {phrase}
                </button>
                {mark.note && <p className="mt-2 [overflow-wrap:anywhere]">{mark.note}</p>}
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={buttonClass('quiet')}
                    aria-label={`Edit mark ${phrase}`}
                    onClick={() => onEdit(mark)}
                  >
                    Edit note
                  </button>
                  <button
                    type="button"
                    className={buttonClass('quiet')}
                    aria-label={`Remove mark ${phrase}`}
                    onClick={() => onRemove(mark)}
                  >
                    Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
