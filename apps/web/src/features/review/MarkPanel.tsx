import { useEffect, useRef, useState, type RefObject } from 'react';

import { buttonClass } from '../../components/button';
import { SaveStatus, saveStatusText } from '../../lib/autosave';
import type { LocalMark, MarkSyncStatus } from './markSync';
import { STICKY_HEADER_CLEARANCE } from '../session/PracticeLayout';
import { MAX_MARK_WORDS, rangeOf, type Range, type Selection } from './selection';

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
  markCount,
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
  markCount: number;
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
  const full = range !== null && range.word_to - range.word_from + 1 >= MAX_MARK_WORDS;
  const section = useRef<HTMLElement>(null);
  // Sticky while words are chosen; with a note editor open it is too tall to float, so it
  // scrolls with the page (360 px screens would lose much of the transcript).
  const sticky = !mark;
  useStickyClearance(section, sticky);
  const [announcedCount, setAnnouncedCount] = useState(markCount);
  useEffect(() => {
    const timer = setTimeout(() => setAnnouncedCount(markCount), 1000);
    return () => clearTimeout(timer);
  }, [markCount]);
  return (
    <section
      ref={section}
      data-sticky={sticky}
      aria-label="Mark words"
      className={`${sticky ? 'sticky top-[4.5rem] z-[9]' : ''} flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-3`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold">Mark what you did not hear</h3>
        <p>
          {markCount} {markCount === 1 ? 'mark' : 'marks'}
        </p>
        <span aria-hidden={status.kind === 'failed' || undefined}>
          <SaveStatus status={status} noun="Marks" className="text-body-s" />
        </span>
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
              disabled={range.word_from === 0 || full}
              onClick={() => onSelect({ anchor: range.word_to, focus: range.word_from - 1 })}
            >
              Add previous word
            </button>
            <button
              type="button"
              className={buttonClass('secondary')}
              disabled={range.word_to >= wordCount - 1 || full}
              onClick={() => onSelect({ anchor: range.word_from, focus: range.word_to + 1 })}
            >
              Add next word
            </button>
          </div>
          {full && <p className="text-body-s">A mark covers at most {MAX_MARK_WORDS} words.</p>}
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
        <span>
          {announcedCount} {announcedCount === 1 ? 'mark' : 'marks'}.
        </span>{' '}
        <span>{status.kind === 'failed' ? saveStatusText(status, 'Marks') : announcement}</span>
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

/**
 * The panel sticks just below the practice header, so a word that scrolls under it would
 * have the keyboard focus without being seen (WCAG 2.4.11). The page's `scroll-padding-top`
 * (the header, `PracticeLayout`) is raised by the panel's height, so the browser scrolls a
 * focused word clear of both. The panel grows when the note editor opens, so its height is
 * followed. The first measurement comes after the layout has set its own padding.
 */
function useStickyClearance(panel: RefObject<HTMLElement | null>, sticky: boolean) {
  useEffect(() => {
    const element = panel.current;
    if (!sticky || !element || typeof ResizeObserver === 'undefined') return;
    const root = document.documentElement;
    let applied = '';
    const observer = new ResizeObserver(() => {
      root.style.scrollPaddingTop = `calc(${STICKY_HEADER_CLEARANCE} + ${element.offsetHeight + 8}px)`;
      applied = root.style.scrollPaddingTop; // as the browser reports it back
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      // When the whole screen goes, the layout has already put the page's value back.
      if (root.style.scrollPaddingTop === applied)
        root.style.scrollPaddingTop = STICKY_HEADER_CLEARANCE;
    };
  }, [panel, sticky]);
}
