import type { DiffItem } from './api';
import { candidateRuns, isAdded, isRunAdded, rangesToAddAll } from './marks';

const word = (index: number, status: DiffItem['status'], text = `w${index}`): DiffItem => ({
  index,
  status,
  word: text,
  typed: status === 'missing' ? '' : 'x',
});
const extra: DiffItem = { index: null, status: 'extra', word: '', typed: 'um' };
const mark = (word_from: number, word_to = word_from) => ({ word_from, word_to });

test('missed and wrong words next to each other form one run; others stand alone', () => {
  const items = [
    word(0, 'correct'),
    word(1, 'missing', 'kind'),
    extra,
    word(2, 'wrong', 'of'),
    word(3, 'spelling_slip'),
    word(4, 'missing', 'there'),
    word(5, 'not_scored'),
    word(6, 'wrong', 'then'),
  ];

  expect(candidateRuns(items)).toEqual([
    { word_from: 1, word_to: 2, words: [items[1], items[3]] },
    { word_from: 4, word_to: 4, words: [items[5]] },
    { word_from: 6, word_to: 6, words: [items[7]] },
  ]);
});

test('a diff with nothing missed or wrong has no runs', () => {
  expect(candidateRuns([word(0, 'correct'), extra, word(1, 'spelling_slip')])).toEqual([]);
});

test('a run longer than a mark is split at 20 words', () => {
  const items = Array.from({ length: 45 }, (_, i) => word(i, 'missing'));

  expect(candidateRuns(items).map((r) => [r.word_from, r.word_to])).toEqual([
    [0, 19],
    [20, 39],
    [40, 44],
  ]);
});

test('words count as added only when a mark covers exactly them', () => {
  const marks = [mark(1, 2), mark(4)];

  expect(isAdded(marks, { word_from: 1, word_to: 2 })).toBe(true);
  expect(isAdded(marks, { word_from: 1, word_to: 1 })).toBe(false);
  expect(isAdded(marks, { word_from: 4, word_to: 4 })).toBe(true);
});

describe('add all', () => {
  const runs = candidateRuns([
    word(1, 'missing'),
    word(2, 'missing'),
    word(3, 'missing'),
    word(5, 'wrong'),
    word(7, 'missing'),
    word(8, 'wrong'),
  ]);

  test('adds every run as one mark', () => {
    expect(rangesToAddAll(runs, [])).toEqual([
      { word_from: 1, word_to: 3 },
      { word_from: 5, word_to: 5 },
      { word_from: 7, word_to: 8 },
    ]);
  });

  test('skips a run already added, as a whole or word by word', () => {
    const marks = [mark(1, 3), mark(7), mark(8)];
    expect(rangesToAddAll(runs, marks)).toEqual([{ word_from: 5, word_to: 5 }]);
  });

  test('adds only the other words of a run when some of its words are added alone', () => {
    expect(rangesToAddAll(runs, [mark(2)])).toEqual([
      { word_from: 1, word_to: 1 },
      { word_from: 3, word_to: 3 },
      { word_from: 5, word_to: 5 },
      { word_from: 7, word_to: 8 },
    ]);
  });
});

test('a run counts as added as one mark or when every word is added alone', () => {
  const [run] = candidateRuns([word(1, 'missing'), word(2, 'wrong')]);

  expect(isRunAdded([mark(1, 2)], run)).toBe(true);
  expect(isRunAdded([mark(1), mark(2)], run)).toBe(true);
  expect(isRunAdded([mark(1)], run)).toBe(false);
  expect(isRunAdded([], run)).toBe(false);
});
