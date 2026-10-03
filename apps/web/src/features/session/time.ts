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
