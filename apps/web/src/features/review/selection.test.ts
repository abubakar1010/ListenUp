import {
  MAX_MARK_WORDS,
  extend,
  growFrom,
  markAt,
  moveTo,
  rangeOf,
  reach,
  sameRange,
  select,
  wouldPassLimit,
} from './selection';

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

test('a_selection_is_a_word_or_a_short_phrase_never_more_than_the_limit', () => {
  let selection = select(0);
  for (let i = 0; i < 40; i += 1) selection = extend(selection, 1, 100);
  const range = rangeOf(selection);
  expect(range.word_to - range.word_from + 1).toBe(MAX_MARK_WORDS);
  expect(wouldPassLimit(selection, 1)).toBe(true);
  expect(wouldPassLimit(selection, -1)).toBe(false); // shrinking is always allowed
  expect(rangeOf(extend(selection, -1, 100)).word_to).toBe(MAX_MARK_WORDS - 2);
  expect(wouldPassLimit(select(0), 1)).toBe(false);
});

test('reaching_a_far_word_stops_at_the_limit_from_the_anchor', () => {
  expect(rangeOf(reach(select(10), 14))).toEqual({ word_from: 10, word_to: 14 });
  expect(rangeOf(reach(select(10), 90))).toEqual({
    word_from: 10,
    word_to: 10 + MAX_MARK_WORDS - 1,
  });
  expect(rangeOf(reach(select(50), 0))).toEqual({
    word_from: 50 - MAX_MARK_WORDS + 1,
    word_to: 50,
  });
});

test('a_selection_grows_from_the_word_that_has_the_keyboard_focus', () => {
  const mark = { anchor: 3, focus: 5 }; // arrived on the mark by an arrow, focus on its first word
  expect(growFrom(mark, 3)).toEqual({ anchor: 5, focus: 3 });
  expect(growFrom(mark, 5)).toEqual({ anchor: 3, focus: 5 });
  expect(growFrom(mark, 4)).toEqual({ anchor: 3, focus: 4 });
  expect(growFrom({ anchor: 4, focus: 4 }, 4)).toEqual({ anchor: 4, focus: 4 });
});
