import { extend, markAt, moveTo, rangeOf, sameRange, select } from './selection';

const MARKS = [
  { id: 'm1', word_from: 3, word_to: 5 },
  { id: 'm2', word_from: 4, word_to: 4 },
];

test('a_selection_runs_forwards_whichever_way_it_was_extended', () => {
  expect(rangeOf(select(2))).toEqual({ word_from: 2, word_to: 2 });
  expect(rangeOf(extend(select(4), -2, 10))).toEqual({ word_from: 2, word_to: 4 });
  expect(rangeOf(extend(extend(select(4), 2, 10), -3, 10))).toEqual({ word_from: 3, word_to: 4 });
});

test('extending_stops_at_the_ends_of_the_passage', () => {
  expect(rangeOf(extend(select(0), -1, 3))).toEqual({ word_from: 0, word_to: 0 });
  expect(rangeOf(extend(select(2), 1, 3))).toEqual({ word_from: 2, word_to: 2 });
});

test('moving_onto_a_marked_word_selects_the_smallest_mark_around_it', () => {
  expect(rangeOf(moveTo(4, MARKS))).toEqual({ word_from: 4, word_to: 4 });
  expect(rangeOf(moveTo(5, MARKS))).toEqual({ word_from: 3, word_to: 5 });
  expect(rangeOf(moveTo(4, [MARKS[0]]))).toEqual({ word_from: 3, word_to: 5 });
  expect(rangeOf(moveTo(7, MARKS))).toEqual({ word_from: 7, word_to: 7 });
});

test('the_mark_of_a_selection_is_the_one_with_exactly_its_words', () => {
  expect(markAt(select(4), MARKS)?.id).toBe('m2');
  expect(markAt(extend(select(3), 2, 10), MARKS)?.id).toBe('m1');
  expect(markAt(extend(select(3), 1, 10), MARKS)).toBeUndefined();
  expect(markAt(null, MARKS)).toBeUndefined();
  expect(sameRange({ word_from: 1, word_to: 2 }, { word_from: 1, word_to: 2 })).toBe(true);
});
