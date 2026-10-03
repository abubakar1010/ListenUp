/** Times in the passage controls: "mm:ss" (minutes may pass 59) or "h:mm:ss". */

export const MIN_PASSAGE_MS = 30_000;
export const MAX_PASSAGE_MS = 900_000;

/** 125_000 → "02:05"; 3_725_000 → "1:02:05". Rounds down to the second. */
export function formatClock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${String(minutes).padStart(2, '0')}:${seconds}`;
}

/** 150_000 → "2:30", for lengths. */
export function formatLength(ms: number): string {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** 150_000 → "2 minutes 30 seconds", for screen readers. */
export function spokenLength(ms: number): string {
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  const parts = [];
  if (minutes) parts.push(`${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`);
  if (seconds || !minutes) parts.push(`${seconds} ${seconds === 1 ? 'second' : 'seconds'}`);
  return parts.join(' ');
}

/** "2:05", "02:05", "125" (seconds) or "1:02:05" → milliseconds; null when not a time. */
export function parseClock(text: string): number | null {
  const value = text.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const parts = value.split(':');
  if (parts.length < 2 || parts.length > 3) return null;
  if (!parts.every((part) => /^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  const seconds = numbers[numbers.length - 1];
  if (seconds > 59) return null;
  if (numbers.length === 3 && numbers[1] > 59) return null;
  const total =
    numbers.length === 3
      ? numbers[0] * 3600 + numbers[1] * 60 + seconds
      : numbers[0] * 60 + seconds;
  return total * 1000;
}

export interface PassageCheck {
  start?: string;
  end?: string;
}

/** What is wrong with a passage, per field; empty when it is fine (C2). */
export function checkPassage(
  startText: string,
  endText: string,
  durationMs: number | null,
): { startMs: number | null; endMs: number | null; errors: PassageCheck } {
  const startMs = parseClock(startText);
  const endMs = parseClock(endText);
  const errors: PassageCheck = {};
  if (startMs === null) errors.start = 'Type the start as minutes and seconds, for example 02:10.';
  if (endMs === null) errors.end = 'Type the end as minutes and seconds, for example 04:40.';
  if (startMs === null || endMs === null) return { startMs, endMs, errors };

  if (durationMs !== null && startMs >= durationMs) {
    errors.start = `The start is after the end of the clip (${formatClock(durationMs)}).`;
  } else if (durationMs !== null && endMs > durationMs) {
    errors.end = `The end is after the end of the clip (${formatClock(durationMs)}).`;
  } else if (endMs <= startMs) {
    errors.end = 'The end must come after the start.';
  } else if (endMs - startMs < MIN_PASSAGE_MS) {
    errors.end = `This part is ${spokenLength(endMs - startMs)}. A part needs at least 30 seconds.`;
  } else if (endMs - startMs > MAX_PASSAGE_MS) {
    errors.end = `This part is ${formatLength(endMs - startMs)} long. A part can be 15 minutes at most.`;
  }
  return { startMs, endMs, errors };
}

export type PassageMode = 'whole' | 'part';

export interface PassageValue {
  mode: PassageMode;
  start: string;
  end: string;
}

/** The whole clip when it is 30 s to 15 min long; otherwise its first 15 minutes (C2). */
export function defaultPassage(durationMs: number | null): PassageValue {
  if (durationMs !== null && wholeFits(durationMs)) {
    return { mode: 'whole', start: formatClock(0), end: formatClock(durationMs) };
  }
  const end = durationMs === null ? MAX_PASSAGE_MS : Math.min(durationMs, MAX_PASSAGE_MS);
  return { mode: 'part', start: formatClock(0), end: formatClock(end) };
}

export function wholeFits(durationMs: number): boolean {
  return durationMs >= MIN_PASSAGE_MS && durationMs <= MAX_PASSAGE_MS;
}
