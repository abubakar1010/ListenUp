import { formatClock, formatLength, parseClock, spokenLength } from './time';

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

test('lengths format as m:ss, and in words for screen readers', () => {
  expect(formatLength(150_000)).toBe('2:30');
  expect(spokenLength(150_000)).toBe('2 minutes 30 seconds');
  expect(spokenLength(61_000)).toBe('1 minute 1 second');
  expect(spokenLength(0)).toBe('0 seconds');
});
