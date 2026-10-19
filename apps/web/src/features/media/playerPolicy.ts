/**
 * The Dictation player's control policy (FR-DI-1, FR-DI-2, NFR-PERF-4; final design
 * E01; ADR 0025). The mirror of the server's rules: Dictation may replay, seek and slow
 * down as much as the learner likes, but only inside the passage, and never shows text.
 *
 * Positions are milliseconds from the start of the passage, not of the clip.
 */

/** Speeds offered, default first (FR-DI-2: "a slower speed option (default 1x)"). */
export const SPEEDS = [1, 0.9, 0.75] as const;
export type Speed = (typeof SPEEDS)[number];
export const DEFAULT_SPEED: Speed = 1;

/**
 * "The last segment" of FR-DI-2. Before a transcript exists there are no sentences, so
 * the passage is cut into 8-second segments (design E01, "Before the transcript exists").
 */
export const SEGMENT_MS = 8000;

/** "Back 5 s" (design E01). */
export const BACK_MS = 5000;

/** Within this much of a segment's start, "Replay segment" goes to the one before. */
export const REPLAY_GRACE_MS = 1000;

export function clamp(positionMs: number, durationMs: number): number {
  return Math.min(Math.max(0, positionMs), durationMs);
}

export interface Segment {
  /** 1-based, for "Segment 4 of 12". */
  number: number;
  count: number;
  startMs: number;
  endMs: number;
}

export function segmentAt(positionMs: number, durationMs: number): Segment {
  const count = Math.max(1, Math.ceil(durationMs / SEGMENT_MS));
  const index = Math.min(count - 1, Math.floor(clamp(positionMs, durationMs) / SEGMENT_MS));
  return {
    number: index + 1,
    count,
    startMs: index * SEGMENT_MS,
    endMs: Math.min(durationMs, (index + 1) * SEGMENT_MS),
  };
}

/**
 * Where "Replay segment" starts: the start of the segment being heard, or of the one
 * before when the learner is just past a boundary (they want what they just heard).
 */
export function replayStart(positionMs: number, durationMs: number): number {
  const segment = segmentAt(positionMs, durationMs);
  const into = clamp(positionMs, durationMs) - segment.startMs;
  if (into < REPLAY_GRACE_MS && segment.number > 1) return segment.startMs - SEGMENT_MS;
  if (positionMs >= durationMs && durationMs > 0) {
    return segmentAt(durationMs - 1, durationMs).startMs; // at the end: the last segment
  }
  return segment.startMs;
}

/** The next slower (step 1) or faster (step -1) speed, staying within SPEEDS. */
export function stepSpeed(current: Speed, step: 1 | -1): Speed {
  const index = SPEEDS.indexOf(current);
  return SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, index + step))]!;
}

export function speedLabel(speed: Speed): string {
  return `${speed}x`;
}

/** Which player action a key press asks for, or null (design E01, UX-07). */
export type PlayerAction = 'toggle' | 'back' | 'replay' | 'slower' | 'faster';

export interface KeyPress {
  key: string;
  code: string;
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}

/**
 * Outside the text area: Space or K play and pause, J goes back 5 s, R replays the
 * segment, [ and ] change speed. In the text area, where letters are text: Esc plays
 * and pauses, and Ctrl+Alt (Ctrl+Option on a Mac) with J, R, [ or ]. Never Ctrl+R
 * (reload) or Ctrl+Space (the macOS input switch). Keys are matched by position
 * (`code`), so they work on any keyboard layout.
 */
export function actionFor(press: KeyPress, inTextArea: boolean): PlayerAction | null {
  if (press.metaKey) return null;
  const chord = press.ctrlKey && press.altKey && !press.shiftKey;
  const byCode: Record<string, PlayerAction> = {
    KeyJ: 'back',
    KeyR: 'replay',
    BracketLeft: 'slower',
    BracketRight: 'faster',
  };
  if (chord) return byCode[press.code] ?? null;
  if (inTextArea) return press.key === 'Escape' ? 'toggle' : null;
  if (press.ctrlKey || press.altKey) return null;
  if (press.code === 'Space' || press.code === 'KeyK') return 'toggle';
  return byCode[press.code] ?? null;
}

/** "02:30" for a position in milliseconds. */
export function clock(ms: number): string {
  const total = Math.floor(Math.max(0, ms) / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/** "48 seconds of 2 minutes 30" for the seek slider's aria-valuetext. */
export function spokenTime(ms: number): string {
  const total = Math.floor(Math.max(0, ms) / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes === 0) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const m = `${minutes} minute${minutes === 1 ? '' : 's'}`;
  return seconds ? `${m} ${seconds}` : m;
}
