import { MAX_MARK_WORDS, type Range, sameRange } from '../review/selection';
import type { DiffItem } from './api';

/**
 * Missed and wrong words of the diff next to each other in the passage: what the learner
 * can add to the mark list (#55, FR-DI-6). Only these are mark candidates (ADR 0019); the
 * API refuses any other word.
 */
export interface Run extends Range {
  words: DiffItem[];
}

const isCandidate = (item: DiffItem) => item.status === 'missing' || item.status === 'wrong';

/** The runs in passage order, split where a mark would pass 20 words. */
export function candidateRuns(items: DiffItem[]): Run[] {
  const runs: Run[] = [];
  let run: Run | null = null;
  for (const item of items) {
    if (item.index === null) continue; // an extra word sits between passage words
    if (!isCandidate(item)) {
      run = null;
      continue;
    }
    if (run && item.index === run.word_to + 1 && run.words.length < MAX_MARK_WORDS) {
      run.word_to = item.index;
      run.words.push(item);
    } else {
      run = { word_from: item.index, word_to: item.index, words: [item] };
      runs.push(run);
    }
  }
  return runs;
}

/** A mark covers exactly these words. */
export function isAdded(marks: Range[], range: Range): boolean {
  return marks.some((mark) => sameRange(mark, range));
}

/**
 * "Add all": each run as one mark, unless it is added already, as a whole or word by
 * word. A run with some words added alone adds its other words alone, so no word gets a
 * second, overlapping mark.
 */
export function rangesToAddAll(runs: Run[], marks: Range[]): Range[] {
  const ranges: Range[] = [];
  for (const run of runs) {
    if (isAdded(marks, run)) continue;
    const single = run.words.map((w) => ({ word_from: w.index!, word_to: w.index! }));
    const alone = single.filter((range) => isAdded(marks, range));
    if (alone.length === 0) ranges.push({ word_from: run.word_from, word_to: run.word_to });
    else ranges.push(...single.filter((range) => !isAdded(marks, range)));
  }
  return ranges;
}
