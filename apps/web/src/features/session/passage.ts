/**
 * The passage selection on the start-a-plan page (#42, ADR 0026), as pure functions:
 * limits, clamping, snapping, defaults, first-speech detection and the messages shown
 * when a typed time is adjusted. Every passage is 30 s to 15 min and inside the clip
 * (C2, D2, D15); the server checks the same rules (ADR 0023).
 */
import {
  formatClock,
  formatLength,
  MAX_PASSAGE_MS,
  MIN_PASSAGE_MS,
  parseClock,
  spokenLength,
} from './time';

export { MAX_PASSAGE_MS, MIN_PASSAGE_MS };

/** The suggested part when the whole clip cannot be used, or is long: 2:30 (B04). */
export const SUGGESTED_PASSAGE_MS = 150_000;
/** Arrow keys move a handle 1 s; Shift + arrow, Page Up and Page Down move it 5 s (B04). */
export const SMALL_STEP_MS = 1000;
export const LARGE_STEP_MS = 5000;
/** "Hear start" and "Hear end" play 1.5 s before to 1.5 s after the cut (B04, UX-11). */
export const PREVIEW_HALF_MS = 1500;

/**
 * First speech: the first moment the level stays at or above 10 % of the peaks' scale for
 * half a second, minus a half-second lead-in so the first syllable is not cut. Room tone
 * and hiss in a usable recording sit well under 10 %; speech sits well above it.
 */
export const SPEECH_LEVEL = 0.1;
export const SPEECH_HOLD_MS = 500;
export const SPEECH_LEAD_IN_MS = 500;

/** Drag snap steps; a drag uses the smallest one at least one pixel wide. */
const DRAG_STEPS_MS = [1000, 5000, 10_000, 15_000, 30_000, 60_000];

export type Handle = 'start' | 'end';

export interface Range {
  startMs: number;
  endMs: number;
}

export interface Peaks {
  perSecond: number;
  scale: number;
  values: number[];
}

/** The conversion job's peaks file (ADR 0022); null when it is not that shape. */
export function parsePeaks(json: unknown): Peaks | null {
  if (typeof json !== 'object' || json === null) return null;
  const { version, per_second: perSecond, scale, peaks } = json as Record<string, unknown>;
  if (version !== 1) return null;
  if (typeof perSecond !== 'number' || !(perSecond > 0)) return null;
  if (typeof scale !== 'number' || !(scale > 0)) return null;
  if (!Array.isArray(peaks) || !peaks.every((p) => typeof p === 'number')) return null;
  return { perSecond, scale, values: peaks as number[] };
}

/** Where speech starts, rounded down to the second; null when nothing reaches the level. */
export function firstSpeechMs(peaks: Peaks): number | null {
  const level = SPEECH_LEVEL * peaks.scale;
  const hold = Math.max(1, Math.round((SPEECH_HOLD_MS / 1000) * peaks.perSecond));
  let run = 0;
  for (let i = 0; i < peaks.values.length; i += 1) {
    run = peaks.values[i] >= level ? run + 1 : 0;
    if (run === hold) {
      const onsetMs = ((i - hold + 1) / peaks.perSecond) * 1000;
      return Math.max(0, Math.floor((onsetMs - SPEECH_LEAD_IN_MS) / 1000) * 1000);
    }
  }
  return null;
}

/** The loudest value in each of `count` equal buckets, from 0 to 1 of the clip's loudest. */
export function bucketPeaks(peaks: Peaks, count: number): number[] {
  const { values } = peaks;
  if (values.length === 0 || count <= 0) return [];
  const loudest = Math.max(1, ...values);
  const n = Math.min(count, values.length);
  const out: number[] = [];
  for (let b = 0; b < n; b += 1) {
    const from = Math.floor((b * values.length) / n);
    const to = Math.max(from + 1, Math.floor(((b + 1) * values.length) / n));
    let max = 0;
    for (let i = from; i < to; i += 1) max = Math.max(max, values[i]);
    out.push(max / loudest);
  }
  return out;
}

export function wholeFits(durationMs: number): boolean {
  return durationMs >= MIN_PASSAGE_MS && durationMs <= MAX_PASSAGE_MS;
}

/**
 * The suggested part: 2:30 from the first speech (or from 0 when it is not known), moved
 * back so it ends inside the clip; the whole clip when that is 2:30 or shorter.
 */
export function defaultRange(durationMs: number, speechMs: number | null): Range {
  if (durationMs <= SUGGESTED_PASSAGE_MS) return { startMs: 0, endMs: durationMs };
  const latest = Math.floor((durationMs - SUGGESTED_PASSAGE_MS) / 1000) * 1000;
  const startMs = Math.max(0, Math.min(speechMs ?? 0, latest));
  return { startMs, endMs: startMs + SUGGESTED_PASSAGE_MS };
}

/** Where a handle may go while the other stays put: 30 s to 15 min, inside the clip. */
export function handleBounds(
  range: Range,
  handle: Handle,
  durationMs: number,
): { min: number; max: number } {
  if (handle === 'start') {
    return {
      min: Math.max(0, range.endMs - MAX_PASSAGE_MS),
      max: Math.max(0, range.endMs - MIN_PASSAGE_MS),
    };
  }
  return {
    min: Math.min(durationMs, range.startMs + MIN_PASSAGE_MS),
    max: Math.min(durationMs, range.startMs + MAX_PASSAGE_MS),
  };
}

/** Moves one handle to `ms`; it stops at its bounds, so the passage stays valid. */
export function moveHandle(range: Range, handle: Handle, ms: number, durationMs: number): Range {
  const { min, max } = handleBounds(range, handle, durationMs);
  const value = Math.min(max, Math.max(min, Math.round(ms)));
  return handle === 'start' ? { ...range, startMs: value } : { ...range, endMs: value };
}

/** The handle a press on the track moves: the nearer one; when level, by the side. */
export function nearerHandle(range: Range, ms: number): Handle {
  const toStart = Math.abs(ms - range.startMs);
  const toEnd = Math.abs(ms - range.endMs);
  if (toStart !== toEnd) return toStart < toEnd ? 'start' : 'end';
  return ms <= range.startMs ? 'start' : 'end';
}

/** The drag snap for a clip drawn `widthPx` wide: whole seconds, coarser on long clips. */
export function dragStepMs(durationMs: number, widthPx: number): number {
  if (!(widthPx > 0)) return DRAG_STEPS_MS[0];
  const msPerPx = durationMs / widthPx;
  return DRAG_STEPS_MS.find((step) => step >= msPerPx) ?? DRAG_STEPS_MS.at(-1)!;
}

/** Rounds to the nearest step; within half a step of the clip's end, the end itself. */
export function snapMs(ms: number, stepMs: number, durationMs: number): number {
  if (ms >= durationMs - stepMs / 2) return durationMs;
  return Math.max(0, Math.round(ms / stepMs) * stepMs);
}

/**
 * Where a key moves a focused handle (the slider pattern): arrows by 1 s, with Shift or
 * Page Up/Down by 5 s, to the next whole step; Home and End to the furthest the handle
 * can go. Null for other keys. The result still needs `moveHandle` to clamp it.
 */
export function keyTarget(
  value: number,
  key: string,
  shiftKey: boolean,
  bounds: { min: number; max: number },
): number | null {
  const step = shiftKey || key === 'PageUp' || key === 'PageDown' ? LARGE_STEP_MS : SMALL_STEP_MS;
  switch (key) {
    case 'ArrowRight':
    case 'ArrowUp':
    case 'PageUp':
      return Math.floor(value / step) * step + step;
    case 'ArrowLeft':
    case 'ArrowDown':
    case 'PageDown':
      return Math.ceil(value / step) * step - step;
    case 'Home':
      return bounds.min;
    case 'End':
      return bounds.max;
    default:
      return null;
  }
}

/** The stretch "Hear start" or "Hear end" plays around a cut, inside the clip. */
export function previewWindow(cutMs: number, durationMs: number): { fromMs: number; toMs: number } {
  return {
    fromMs: Math.max(0, cutMs - PREVIEW_HALF_MS),
    toMs: Math.min(durationMs, cutMs + PREVIEW_HALF_MS),
  };
}

export interface TypedResult {
  range: Range;
  /** The text could not be read as a time; the range is unchanged. */
  error?: string;
  /** The time was adjusted to keep the passage valid, and how. */
  note?: string;
}

/**
 * Applies a typed start or end. A time past the clip is set to the latest allowed; then
 * the end gives way: a typed end is set to make the part 30 s to 15 min, and a typed start
 * moves the end along when the part would leave those limits (B04: values clamp with a
 * message, so the selection is always valid).
 */
export function applyTyped(
  range: Range,
  handle: Handle,
  text: string,
  durationMs: number,
): TypedResult {
  const typed = parseClock(text);
  if (typed === null) {
    return {
      range,
      error: `Type the ${handle} as minutes and seconds, for example ${handle === 'start' ? '02:10' : '04:40'}.`,
    };
  }
  const shown = text.trim();
  const notes: string[] = [];
  if (handle === 'start') {
    let startMs = typed;
    const latest = durationMs - MIN_PASSAGE_MS;
    if (startMs > latest) {
      startMs = latest;
      notes.push(
        `${shown} leaves less than 30 seconds of the clip, so we set the start to ${formatClock(startMs)}.`,
      );
    }
    let endMs = range.endMs;
    if (endMs - startMs < MIN_PASSAGE_MS) {
      endMs = startMs + MIN_PASSAGE_MS;
      notes.push(`We moved the end to ${formatClock(endMs)} so the part is at least 30 seconds.`);
    } else if (endMs - startMs > MAX_PASSAGE_MS) {
      endMs = startMs + MAX_PASSAGE_MS;
      notes.push(`We moved the end to ${formatClock(endMs)} so the part is 15 minutes at most.`);
    }
    return withNote({ startMs, endMs }, notes);
  }

  let endMs = typed;
  if (endMs > durationMs) {
    endMs = durationMs;
    notes.push(
      `${shown} is after the end of the clip, so we set the end to ${formatClock(endMs)}.`,
    );
  }
  const { startMs } = range;
  const length = endMs - startMs;
  if (length <= 0) {
    endMs = startMs + MIN_PASSAGE_MS;
    notes.push(`The end must come after the start, so we set the end to ${formatClock(endMs)}.`);
  } else if (length < MIN_PASSAGE_MS) {
    endMs = startMs + MIN_PASSAGE_MS;
    notes.push(
      `This part is ${spokenLength(length)}. A part needs at least 30 seconds, so we set the end to ${formatClock(endMs)}.`,
    );
  } else if (length > MAX_PASSAGE_MS) {
    endMs = startMs + MAX_PASSAGE_MS;
    notes.push(
      `Start ${formatClock(startMs)} to end ${formatClock(typed)} makes ${formatLength(length)}. A part can be 15 minutes at most, so we set the end to ${formatClock(endMs)}.`,
    );
  }
  return withNote({ startMs, endMs }, notes);
}

function withNote(range: Range, notes: string[]): TypedResult {
  return notes.length ? { range, note: notes.join(' ') } : { range };
}

/** "2 minutes 10 seconds", for a handle's position as a screen reader says it. */
export function spokenTime(ms: number): string {
  return spokenLength(Math.floor(ms / 1000) * 1000);
}
