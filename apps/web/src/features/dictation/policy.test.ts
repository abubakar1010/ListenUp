import {
  SPEEDS,
  actionFor,
  clamp,
  clock,
  replayStart,
  segmentAt,
  spokenTime,
  stepSpeed,
  type KeyPress,
} from './policy';

const press = (code: string, extra: Partial<KeyPress> = {}): KeyPress => ({
  key: code.replace(/^Key/, '').toLowerCase(),
  code,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  shiftKey: false,
  ...extra,
});

test('the speeds are 1x by default with slower choices only', () => {
  expect(SPEEDS[0]).toBe(1);
  expect(SPEEDS.every((speed) => speed <= 1)).toBe(true);
  expect(SPEEDS).toContain(0.75);
});

test('positions never leave the passage', () => {
  expect(clamp(-500, 150_000)).toBe(0);
  expect(clamp(160_000, 150_000)).toBe(150_000);
  expect(clamp(48_000, 150_000)).toBe(48_000);
});

test('a 2:30 passage has 19 segments of 8 s, the last one shorter', () => {
  expect(segmentAt(48_000, 150_000)).toEqual({
    number: 7,
    count: 19,
    startMs: 48_000,
    endMs: 56_000,
  });
  expect(segmentAt(150_000, 150_000)).toEqual({
    number: 19,
    count: 19,
    startMs: 144_000,
    endMs: 150_000,
  });
});

test('replay goes to the start of the segment being heard', () => {
  expect(replayStart(52_500, 150_000)).toBe(48_000);
});

test('just past a boundary, replay goes to the segment just heard', () => {
  expect(replayStart(48_400, 150_000)).toBe(40_000);
  expect(replayStart(300, 150_000)).toBe(0);
});

test('at the end of the passage, replay plays the last segment', () => {
  expect(replayStart(150_000, 150_000)).toBe(144_000);
});

test('speed steps stop at the slowest and the fastest', () => {
  expect(stepSpeed(1, 1)).toBe(0.9);
  expect(stepSpeed(0.75, 1)).toBe(0.75);
  expect(stepSpeed(1, -1)).toBe(1);
});

test('single keys work outside the text area only', () => {
  expect(actionFor(press('Space', { key: ' ' }), false)).toBe('toggle');
  expect(actionFor(press('KeyK'), false)).toBe('toggle');
  expect(actionFor(press('KeyJ'), false)).toBe('back');
  expect(actionFor(press('KeyR'), false)).toBe('replay');
  expect(actionFor(press('BracketLeft', { key: '[' }), false)).toBe('slower');
  expect(actionFor(press('BracketRight', { key: ']' }), false)).toBe('faster');
  expect(actionFor(press('KeyJ'), true)).toBeNull();
  expect(actionFor(press('Space', { key: ' ' }), true)).toBeNull();
});

test('in the text area, Esc and Ctrl+Alt chords control the player', () => {
  expect(actionFor(press('Escape', { key: 'Escape' }), true)).toBe('toggle');
  expect(actionFor(press('KeyR', { ctrlKey: true, altKey: true }), true)).toBe('replay');
  expect(actionFor(press('KeyJ', { ctrlKey: true, altKey: true }), true)).toBe('back');
});

test('browser and system shortcuts are left alone', () => {
  expect(actionFor(press('KeyR', { ctrlKey: true }), false)).toBeNull(); // reload
  expect(actionFor(press('Space', { key: ' ', ctrlKey: true }), true)).toBeNull(); // input switch
  expect(actionFor(press('KeyR', { metaKey: true }), false)).toBeNull();
});

test('times read as clocks and as speech', () => {
  expect(clock(48_900)).toBe('00:48');
  expect(clock(150_000)).toBe('02:30');
  expect(spokenTime(48_000)).toBe('48 seconds');
  expect(spokenTime(150_000)).toBe('2 minutes 30');
  expect(spokenTime(60_000)).toBe('1 minute');
});
