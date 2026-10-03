import { checkPassage, defaultPassage, formatClock, parseClock } from './time';

test('times parse as m:ss, mm:ss, h:mm:ss or plain seconds', () => {
  expect(parseClock('2:05')).toBe(125_000);
  expect(parseClock(' 02:05 ')).toBe(125_000);
  expect(parseClock('38:05')).toBe(2_285_000);
  expect(parseClock('1:02:05')).toBe(3_725_000);
  expect(parseClock('90')).toBe(90_000);
  for (const bad of ['', '2:60', '1:60:00', 'a:bc', '1:2:3:4', '-1:00']) {
    expect(parseClock(bad)).toBeNull();
  }
});

test('times format as mm:ss, with hours when needed', () => {
  expect(formatClock(125_999)).toBe('02:05');
  expect(formatClock(3_725_000)).toBe('1:02:05');
});

test('the default passage is the whole clip from 30 s to 15 min, else the first 15 min', () => {
  expect(defaultPassage(600_000)).toEqual({ mode: 'whole', start: '00:00', end: '10:00' });
  expect(defaultPassage(900_000)).toEqual({ mode: 'whole', start: '00:00', end: '15:00' });
  expect(defaultPassage(2_285_000)).toEqual({ mode: 'part', start: '00:00', end: '15:00' });
  expect(defaultPassage(null)).toEqual({ mode: 'part', start: '00:00', end: '15:00' });
});

test('a passage is 30 s to 15 min and inside the clip (C2)', () => {
  expect(checkPassage('00:00', '00:30', 600_000).errors).toEqual({});
  expect(checkPassage('00:00', '15:00', null).errors).toEqual({});
  expect(checkPassage('00:00', '00:29', 600_000).errors.end).toMatch(/at least 30 seconds/);
  expect(checkPassage('00:00', '15:01', null).errors.end).toMatch(/15 minutes at most/);
  expect(checkPassage('05:00', '04:00', 600_000).errors.end).toBe(
    'The end must come after the start.',
  );
  expect(checkPassage('10:00', '10:30', 600_000).errors.start).toMatch(/after the end of the clip/);
  expect(checkPassage('x', '1:00', 600_000).errors.start).toMatch(/minutes and seconds/);
});
