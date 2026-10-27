import { buttonClass } from '../../components/button';
import { formatClock } from '../session/time';
import type { LocalMark, MarkTag } from './markSync';
import { TagSelect } from './TagSelect';
import { TAG_LABELS } from './tags';

/**
 * Where a mark came from, whether it waits for the learner (FR-TR-3) and its tag
 * (FR-TR-4), in words.
 */
function markOrigin(mark: LocalMark): string {
  const origin =
    mark.source !== 'dictation'
      ? 'Your mark'
      : mark.status === 'suggested'
        ? 'From Dictation · To confirm'
        : 'From Dictation';
  return mark.tag ? `${origin} · ${TAG_LABELS[mark.tag]}` : origin;
}

/**
 * FR-TR-5: one audio-ordered list of the same local marks highlighted in the text.
 * FR-TR-3: marks pre-filled from Dictation say so, and each one still to confirm has a
 * Confirm button beside Remove. FR-TR-4: each mark's tag is shown and can be chosen here.
 */
export function MarkList({
  marks,
  phraseOf,
  onPlay,
  onEdit,
  onConfirm,
  onRemove,
  onTag,
}: {
  marks: LocalMark[];
  phraseOf: (mark: LocalMark) => string;
  onPlay: (mark: LocalMark) => void;
  onEdit: (mark: LocalMark) => void;
  onConfirm: (mark: LocalMark) => void;
  onRemove: (mark: LocalMark) => void;
  onTag: (mark: LocalMark, tag: MarkTag | null) => void;
}) {
  const toConfirm = marks.filter((mark) => mark.status === 'suggested').length;
  return (
    <section
      aria-label="Your marks"
      className="flex min-w-0 flex-col gap-3 rounded-md border border-line p-3"
    >
      <h3 className="font-bold">Your marks</h3>
      <p className="text-body-s">
        Enter plays a mark. E edits its note. Delete removes it; Undo brings it back.
      </p>
      {toConfirm > 0 && (
        <p className="text-body-s">
          {toConfirm} {toConfirm === 1 ? 'mark' : 'marks'} from Dictation to confirm. Play each one,
          then Confirm it if you still miss the sound, or Remove it.
        </p>
      )}
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
                  id={`mark-play-${mark.id}`}
                  className={buttonClass(
                    'secondary',
                    'w-full text-left whitespace-normal [overflow-wrap:anywhere]',
                  )}
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
                  {/* The name holds the visible words, so speech input finds it (WCAG 2.5.3);
                      the dot only separates them on screen. */}
                  <span className="sr-only">Play mark</span> {formatClock(mark.at_ms)}{' '}
                  <span aria-hidden="true">·</span> {phrase}
                </button>
                <p className="mt-2 text-body-s font-bold">{markOrigin(mark)}</p>
                {mark.note && <p className="mt-2 [overflow-wrap:anywhere]">{mark.note}</p>}
                <div className="mt-2">
                  <TagSelect
                    id={`mark-list-tag-${mark.id}`}
                    label={
                      <>
                        Tag <span className="sr-only">for mark {phrase}</span>
                      </>
                    }
                    value={mark.tag}
                    onChange={(tag) => onTag(mark, tag)}
                  />
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {mark.status === 'suggested' && (
                    <button
                      type="button"
                      className={buttonClass('secondary')}
                      aria-label={`Confirm mark ${phrase}`}
                      onClick={() => {
                        onConfirm(mark);
                        // The button goes once the mark is confirmed: keep the focus on its row.
                        document.getElementById(`mark-play-${mark.id}`)?.focus();
                      }}
                    >
                      Confirm
                    </button>
                  )}
                  <button
                    type="button"
                    className={buttonClass('quiet')}
                    aria-label={`Edit note for mark ${phrase}`}
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
