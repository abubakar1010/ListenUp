/**
 * The gist's sentence rule, the same as the server's (`modules/blind/domain/gist.py`):
 * a sentence ends with ".", "!" or "?" followed by a space or the end of the text, and
 * has at least 3 words. Text after the last such mark does not count yet.
 */

export const MIN_SENTENCES = 3;
export const MAX_GIST_CHARS = 2_000;
const MIN_WORDS = 3;

const END = /[.!?]+(?=\s|$)/gu;
const WORD = /[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu;

export function countSentences(text: string): number {
  let count = 0;
  let start = 0;
  for (const end of text.matchAll(END)) {
    const words = text.slice(start, end.index).match(WORD) ?? [];
    if (words.length >= MIN_WORDS) count += 1;
    start = end.index + end[0].length;
  }
  return count;
}

/** The live count under the gist box (final UI D04). */
export function sentenceStatus(count: number): string {
  if (count >= MIN_SENTENCES) return `${count} sentences. Ready to submit.`;
  const missing = MIN_SENTENCES - count;
  return `${count} of ${MIN_SENTENCES} sentences. Write ${missing === 1 ? 'one more' : `${missing} more`}.`;
}
