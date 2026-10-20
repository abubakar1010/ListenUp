/**
 * Which passage words the learner has selected for marking (#58, FR-TR-2, UI-4).
 *
 * A selection keeps the word it started from (`anchor`) and the word it reaches
 * (`focus`), so Shift+Arrow can grow or shrink it from either side. Moving onto a
 * marked word selects the smallest mark around it, so a click or an arrow reaches the
 * mark's note; Shift+Arrow still selects any words. Keyboard focus is the screen's
 * concern: it stays on the word the learner moved to.
 */

export interface Range {
  word_from: number;
  word_to: number;
}

export interface Selection {
  anchor: number;
  focus: number;
}

export function select(word: number): Selection {
  return { anchor: word, focus: word };
}

export function rangeOf(selection: Selection): Range {
  return {
    word_from: Math.min(selection.anchor, selection.focus),
    word_to: Math.max(selection.anchor, selection.focus),
  };
}

/** Move the focus end by `step` words, staying inside the passage of `count` words. */
export function extend(selection: Selection, step: number, count: number): Selection {
  return { ...selection, focus: Math.min(count - 1, Math.max(0, selection.focus + step)) };
}

export function sameRange(a: Range, b: Range): boolean {
  return a.word_from === b.word_from && a.word_to === b.word_to;
}

/** Select `word`, or the whole of the smallest mark that covers it. */
export function moveTo(word: number, marks: readonly Range[]): Selection {
  const around = marks
    .filter((mark) => mark.word_from <= word && word <= mark.word_to)
    .sort((a, b) => a.word_to - a.word_from - (b.word_to - b.word_from))[0];
  if (!around) return select(word);
  return { anchor: around.word_from, focus: around.word_to };
}

/** The mark with exactly the selected words, if there is one. */
export function markAt<M extends Range>(
  selection: Selection | null,
  marks: readonly M[],
): M | undefined {
  if (!selection) return undefined;
  const range = rangeOf(selection);
  return marks.find((mark) => sameRange(mark, range));
}
