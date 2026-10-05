import {
  applyTyped,
  bucketPeaks,
  defaultRange,
  dragStepMs,
  firstSpeechMs,
  handleBounds,
  keyTarget,
  moveHandle,
  nearerHandle,
  parsePeaks,
  previewWindow,
  snapMs,
  wholeFits,
  type Peaks,
} from './passage';

/** Ten peaks a second: `silentS` seconds at level 3, then speech at 60 (of 100). */
function peaks(silentS: number, totalS: number): Peaks {
  const values = Array.from({ length: totalS * 10 }, (_, i) => (i < silentS * 10 ? 3 : 60));
  return { perSecond: 10, scale: 100, values };
}

test('the peaks file is read only in the conversion job’s format', () => {
  expect(parsePeaks({ version: 1, per_second: 10, scale: 100, peaks: [0, 5, 100] })).toEqual({
    perSecond: 10,
    scale: 100,
    values: [0, 5, 100],
  });
  for (const bad of [
    null,
    'peaks',
    { version: 2, per_second: 10, scale: 100, peaks: [] },
    { version: 1, per_second: 0, scale: 100, peaks: [] },
    { version: 1, per_second: 10, scale: 100, peaks: ['1'] },
    { version: 1, per_second: 10, scale: 100 },
  ]) {
    expect(parsePeaks(bad)).toBeNull();
  }
});

test('first speech is the first half second at 10 % or more, less a half-second lead-in', () => {
  expect(firstSpeechMs(peaks(12, 300))).toBe(11_000);
  expect(firstSpeechMs(peaks(0, 300))).toBe(0);
  expect(firstSpeechMs(peaks(0.3, 300))).toBe(0);
  // A click shorter than half a second is not speech.
  const click = peaks(20, 300);
  click.values[50] = 90;
  click.values[51] = 90;
  expect(firstSpeechMs(click)).toBe(19_000);
  // The level is relative to the file's scale.
  expect(firstSpeechMs({ perSecond: 10, scale: 1000, values: Array(100).fill(60) })).toBeNull();
  expect(firstSpeechMs({ perSecond: 10, scale: 100, values: Array(100).fill(9) })).toBeNull();
});

test('peaks are bucketed by their loudest value, relative to the clip’s loudest', () => {
  const p = { perSecond: 10, scale: 100, values: [10, 20, 0, 40, 5, 5] };
  expect(bucketPeaks(p, 3)).toEqual([0.5, 1, 0.125]);
  expect(bucketPeaks(p, 100)).toHaveLength(6);
  expect(bucketPeaks({ ...p, values: [] }, 10)).toEqual([]);
  expect(bucketPeaks({ ...p, values: [0, 0] }, 2)).toEqual([0, 0]);
});

test('the whole clip is offered from 30 s to 15 min (C2)', () => {
  expect(wholeFits(29_999)).toBe(false);
  expect(wholeFits(30_000)).toBe(true);
  expect(wholeFits(900_000)).toBe(true);
  expect(wholeFits(900_001)).toBe(false);
});

test('the suggested part is 2:30 from the first speech, inside the clip', () => {
  expect(defaultRange(2_285_000, 11_000)).toEqual({ startMs: 11_000, endMs: 161_000 });
  expect(defaultRange(2_285_000, null)).toEqual({ startMs: 0, endMs: 150_000 });
  // Speech that starts late still leaves a full 2:30 before the end.
  expect(defaultRange(200_500, 120_000)).toEqual({ startMs: 50_000, endMs: 200_000 });
  // A clip of 2:30 or less is suggested whole.
  expect(defaultRange(100_000, 20_000)).toEqual({ startMs: 0, endMs: 100_000 });
});

test('handles stop at 30 s apart, 15 min apart and the clip’s edges', () => {
  const range = { startMs: 600_000, endMs: 750_000 };
  const d = 2_285_000;
  expect(handleBounds(range, 'start', d)).toEqual({ min: 0, max: 720_000 });
  expect(handleBounds(range, 'end', d)).toEqual({ min: 630_000, max: 1_500_000 });
  expect(moveHandle(range, 'start', 740_000, d)).toEqual({ startMs: 720_000, endMs: 750_000 });
  expect(moveHandle(range, 'end', 2_000_000, d)).toEqual({ startMs: 600_000, endMs: 1_500_000 });
  expect(moveHandle(range, 'end', 0, d)).toEqual({ startMs: 600_000, endMs: 630_000 });
  const late = { startMs: 1_500_000, endMs: 2_200_000 };
  expect(moveHandle(late, 'end', 3_000_000, d).endMs).toBe(d);
  expect(moveHandle(late, 'start', -5, d).startMs).toBe(1_300_000);
});

test('drags snap to whole seconds, coarser when a pixel spans more than a second', () => {
  expect(dragStepMs(600_000, 900)).toBe(1000);
  expect(dragStepMs(760_000, 330)).toBe(5000);
  expect(dragStepMs(2_285_000, 330)).toBe(10_000);
  expect(dragStepMs(10 * 3_600_000, 330)).toBe(60_000);
  expect(dragStepMs(600_000, 0)).toBe(1000);
  expect(snapMs(12_400, 1000, 760_437)).toBe(12_000);
  expect(snapMs(12_600, 5000, 760_437)).toBe(15_000);
  expect(snapMs(760_100, 1000, 760_437)).toBe(760_437);
  expect(snapMs(-200, 1000, 760_437)).toBe(0);
});

test('keys move a handle by 1 s, 5 s with Shift or Page keys, and to its limits', () => {
  const bounds = { min: 0, max: 720_000 };
  expect(keyTarget(130_000, 'ArrowRight', false, bounds)).toBe(131_000);
  expect(keyTarget(130_000, 'ArrowUp', false, bounds)).toBe(131_000);
  expect(keyTarget(130_000, 'ArrowLeft', false, bounds)).toBe(129_000);
  expect(keyTarget(130_000, 'ArrowRight', true, bounds)).toBe(135_000);
  expect(keyTarget(131_000, 'ArrowLeft', true, bounds)).toBe(130_000);
  expect(keyTarget(130_000, 'PageUp', false, bounds)).toBe(135_000);
  expect(keyTarget(130_000, 'PageDown', false, bounds)).toBe(125_000);
  // From a position between seconds, to the next whole step.
  expect(keyTarget(760_437, 'ArrowLeft', false, bounds)).toBe(760_000);
  expect(keyTarget(760_437, 'ArrowRight', false, bounds)).toBe(761_000);
  expect(keyTarget(130_000, 'Home', false, bounds)).toBe(0);
  expect(keyTarget(130_000, 'End', false, bounds)).toBe(720_000);
  expect(keyTarget(130_000, 'a', false, bounds)).toBeNull();
});

test('a press on the track moves the nearer handle', () => {
  const range = { startMs: 100_000, endMs: 200_000 };
  expect(nearerHandle(range, 120_000)).toBe('start');
  expect(nearerHandle(range, 180_000)).toBe('end');
  expect(nearerHandle(range, 150_000)).toBe('end');
  const together = { startMs: 100_000, endMs: 100_000 };
  expect(nearerHandle(together, 90_000)).toBe('start');
  expect(nearerHandle(together, 110_000)).toBe('end');
});

test('the checks play 1.5 s either side of the cut, inside the clip', () => {
  expect(previewWindow(130_000, 760_000)).toEqual({ fromMs: 128_500, toMs: 131_500 });
  expect(previewWindow(0, 760_000)).toEqual({ fromMs: 0, toMs: 1500 });
  expect(previewWindow(760_000, 760_000)).toEqual({ fromMs: 758_500, toMs: 760_000 });
});

describe('a typed time', () => {
  const range = { startMs: 130_000, endMs: 280_000 };
  const d = 760_000;

  test('within the limits is used as typed', () => {
    expect(applyTyped(range, 'end', '4:00', d)).toEqual({
      range: { startMs: 130_000, endMs: 240_000 },
    });
    expect(applyTyped(range, 'start', '100', d)).toEqual({
      range: { startMs: 100_000, endMs: 280_000 },
    });
  });

  test('that is not a time is refused with an example', () => {
    expect(applyTyped(range, 'start', 'two', d)).toEqual({
      range,
      error: 'Type the start as minutes and seconds, for example 02:10.',
    });
    expect(applyTyped(range, 'end', '4:75', d).error).toBe(
      'Type the end as minutes and seconds, for example 04:40.',
    );
  });

  test('end making a part under 30 s or before the start is set 30 s after the start', () => {
    expect(applyTyped(range, 'end', '02:25', d)).toEqual({
      range: { startMs: 130_000, endMs: 160_000 },
      note: 'This part is 15 seconds. A part needs at least 30 seconds, so we set the end to 02:40.',
    });
    expect(applyTyped(range, 'end', '01:00', d).note).toBe(
      'The end must come after the start, so we set the end to 02:40.',
    );
  });

  test('end making a part over 15 min is set 15 min after the start', () => {
    const long = { startMs: 300_000, endMs: 450_000 };
    expect(applyTyped(long, 'end', '23:20', 2_285_000)).toEqual({
      range: { startMs: 300_000, endMs: 1_200_000 },
      note: 'Start 05:00 to end 23:20 makes 18:20. A part can be 15 minutes at most, so we set the end to 20:00.',
    });
  });

  test('end after the clip is set to the clip’s end', () => {
    expect(applyTyped(range, 'end', '14:00', d)).toEqual({
      range: { startMs: 130_000, endMs: 760_000 },
      note: '14:00 is after the end of the clip, so we set the end to 12:40.',
    });
  });

  test('start moves the end along to keep 30 s to 15 min', () => {
    expect(applyTyped(range, 'start', '05:00', d)).toEqual({
      range: { startMs: 300_000, endMs: 330_000 },
      note: 'We moved the end to 05:30 so the part is at least 30 seconds.',
    });
    const long = { startMs: 300_000, endMs: 1_200_000 };
    expect(applyTyped(long, 'start', '00:00', 2_285_000)).toEqual({
      range: { startMs: 0, endMs: 900_000 },
      note: 'We moved the end to 15:00 so the part is 15 minutes at most.',
    });
  });

  test('start too near the clip’s end is set 30 s before it', () => {
    expect(applyTyped(range, 'start', '12:30', d)).toEqual({
      range: { startMs: 730_000, endMs: 760_000 },
      note: '12:30 leaves less than 30 seconds of the clip, so we set the start to 12:10. We moved the end to 12:40 so the part is at least 30 seconds.',
    });
  });
});
