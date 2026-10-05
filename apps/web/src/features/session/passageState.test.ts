import {
  commitAll,
  initialPassage,
  passageReducer,
  selectedRange,
  textOf,
  type PassageState,
} from './passageState';

const D = 760_437;
const BASE = { startMs: 11_000, endMs: 161_000 };

function part(overrides: Partial<PassageState> = {}): PassageState {
  return { ...initialPassage(2_285_000), ...overrides };
}

test('a clip of 30 s to 15 min starts as the whole clip, a longer one as a part', () => {
  expect(initialPassage(D).mode).toBe('whole');
  expect(initialPassage(2_285_000).mode).toBe('part');
  expect(selectedRange(initialPassage(D), BASE, D)).toEqual({ startMs: 0, endMs: D });
  expect(selectedRange(part(), BASE, D)).toEqual(BASE);
});

test('until the learner chooses, the part follows the suggestion', () => {
  const state = part();
  expect(textOf(state, BASE, 'start')).toBe('00:11');
  expect(textOf(state, { startMs: 0, endMs: 150_000 }, 'start')).toBe('00:00');
  const moved = passageReducer(state, { type: 'set', range: { startMs: 20_000, endMs: 60_000 } });
  expect(textOf(moved, BASE, 'start')).toBe('00:20');
  expect(textOf(moved, BASE, 'end')).toBe('01:00');
});

test('typing keeps a draft; leaving the field applies it, adjusted with a note', () => {
  let state = passageReducer(part(), { type: 'type', handle: 'end', text: '02:20' });
  expect(textOf(state, BASE, 'end')).toBe('02:20');
  expect(selectedRange(state, BASE, D)).toEqual(BASE);

  state = passageReducer(state, { type: 'commit', handle: 'end', base: BASE, durationMs: D });
  expect(selectedRange(state, BASE, D)).toEqual({ startMs: 11_000, endMs: 140_000 });
  expect(state.note).toBeNull();

  state = passageReducer(state, { type: 'type', handle: 'end', text: '00:20' });
  state = passageReducer(state, { type: 'commit', handle: 'end', base: BASE, durationMs: D });
  expect(textOf(state, BASE, 'end')).toBe('00:41');
  expect(state.note).toEqual({
    handle: 'end',
    text: 'This part is 9 seconds. A part needs at least 30 seconds, so we set the end to 00:41.',
  });

  // Moving a handle clears drafts, errors and notes: the fields follow the handles.
  state = passageReducer(state, { type: 'type', handle: 'start', text: 'x' });
  state = passageReducer(state, { type: 'set', range: { startMs: 0, endMs: 60_000 } });
  expect(state).toMatchObject({ drafts: {}, errors: {}, note: null });
});

test('an unreadable time is an error until it is typed again', () => {
  let state = passageReducer(part(), { type: 'type', handle: 'start', text: 'soon' });
  state = passageReducer(state, { type: 'commit', handle: 'start', base: BASE, durationMs: D });
  expect(state.errors.start).toBe('Type the start as minutes and seconds, for example 02:10.');
  expect(textOf(state, BASE, 'start')).toBe('soon');
  state = passageReducer(state, { type: 'type', handle: 'start', text: '00:3' });
  expect(state.errors.start).toBeUndefined();
});

test('text that still shows the position changes nothing, even off the second', () => {
  const state = part({ custom: { startMs: 610_437, endMs: D }, drafts: { end: '12:40' } });
  const next = passageReducer(state, { type: 'commit', handle: 'end', base: BASE, durationMs: D });
  expect(next.custom).toEqual({ startMs: 610_437, endMs: D });
  expect(next.drafts).toEqual({});
});

test('submitting applies drafts and stops at one that was unreadable or adjusted', () => {
  const plain = commitAll(part({ drafts: { end: '03:00' } }), BASE, D);
  expect(plain.stop).toBeNull();
  expect(selectedRange(plain.state, BASE, D)).toEqual({ startMs: 11_000, endMs: 180_000 });

  const adjusted = commitAll(part({ drafts: { end: '00:20' } }), BASE, D);
  expect(adjusted.stop).toBe('end');

  const unreadable = commitAll(part({ drafts: { start: 'x', end: '03:00' } }), BASE, D);
  expect(unreadable.stop).toBe('start');
  expect(selectedRange(unreadable.state, BASE, D).endMs).toBe(180_000);

  // An earlier error still stops a later submit.
  expect(commitAll(unreadable.state, BASE, D).stop).toBe('start');

  // Drafts left behind in a part do not matter once the whole clip is chosen.
  const whole = { ...unreadable.state, mode: 'whole' as const };
  expect(commitAll(whole, BASE, D).stop).toBeNull();
});
