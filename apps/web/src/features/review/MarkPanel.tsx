import { useEffect, useRef, useState } from 'react';

import { buttonClass } from '../../components/button';
import { SaveStatus } from '../../lib/autosave';
import type { LocalMark, MarkSyncStatus } from './markSync';
import { rangeOf, type Range, type Selection } from './selection';

/**
 * What the learner selected and what they can do with it (#58, FR-TR-2): mark it in one
 * click or tap, grow it a word at a time on a touch screen, or write the note of the mark
 * it already is. The transcript words do the selecting (`TranscriptScreen`).
 */
export function MarkPanel({
  selection,
  phrase,
  mark,
  wordCount,
  status,
  announcement,
  focusNote,
  onSelect,
  onMark,
  onNote,
  onRemove,
  onNoteFocused,
}: {
  selection: Selection | null;
  phrase: string;
  /** The mark with exactly the selected words, if any. */
  mark: LocalMark | undefined;
  wordCount: number;
  status: MarkSyncStatus;
  announcement: string;
  /** True when the note field should take focus (the M key on a marked word). */
  focusNote: boolean;
  onSelect: (selection: Selection) => void;
  onMark: () => void;
  onNote: (id: string, note: string | null) => void;
  onRemove: (id: string) => void;
  onNoteFocused: () => void;
}) {
  const range: Range | null = selection ? rangeOf(selection) : null;
  return (
    <section
      aria-label="Mark words"
      className="sticky top-0 z-10 flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold">Mark what you did not hear</h3>
        <SaveStatus status={status} noun="Marks" className="text-body-s" />
      </div>
      {!range ? (
        <p className="text-body-s">
          Choose a word, then Mark it. With the keyboard: arrows move between words, Shift and an
          arrow select more words, M marks.
        </p>
      ) : (
        <>
          <p>
            {mark ? 'Marked: ' : 'Selected: '}
            <span className="font-bold [overflow-wrap:anywhere]">“{phrase}”</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {!mark && (
              <button type="button" className={buttonClass('primary')} onClick={onMark}>
                Mark
              </button>
            )}
            <button
              type="button"
              className={buttonClass('secondary')}
              disabled={range.word_from === 0}
              onClick={() => onSelect({ anchor: range.word_to, focus: range.word_from - 1 })}
            >
              Add previous word
            </button>
            <button
              type="button"
              className={buttonClass('secondary')}
              disabled={range.word_to >= wordCount - 1}
              onClick={() => onSelect({ anchor: range.word_from, focus: range.word_to + 1 })}
            >
              Add next word
            </button>
          </div>
          {mark && (
            <NoteEditor
              key={mark.id}
              mark={mark}
              focus={focusNote}
              onFocused={onNoteFocused}
              onSave={(note) => onNote(mark.id, note)}
              onRemove={() => onRemove(mark.id)}
            />
          )}
        </>
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

function NoteEditor({
  mark,
  focus,
  onFocused,
  onSave,
  onRemove,
}: {
  mark: LocalMark;
  focus: boolean;
  onFocused: () => void;
  onSave: (note: string | null) => void;
  onRemove: () => void;
}) {
  const [draft, setDraft] = useState(mark.note ?? '');
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!focus) return;
    field.current?.focus();
    onFocused();
  }, [focus, onFocused]);
  const save = () => onSave(draft.trim() || null);
  const id = `mark-note-${mark.id}`;
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="font-bold">
        Note (optional)
      </label>
      <textarea
        ref={field}
        id={id}
        rows={2}
        maxLength={500}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={save}
        className="rounded-sm border border-line p-2"
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass('secondary')} onClick={save}>
          Save note
        </button>
        <button type="button" className={buttonClass('secondary')} onClick={onRemove}>
          Remove mark
        </button>
      </div>
    </div>
  );
}
