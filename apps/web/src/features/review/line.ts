import type { TranscriptLine } from './api';

/** Silence retains the preceding sentence for replay; leading silence has none. */
export function currentLine(lines: TranscriptLine[], absoluteMs: number): TranscriptLine | null {
  let current: TranscriptLine | null = null;
  for (const line of lines) {
    if (line.start_ms > absoluteMs) break;
    current = line;
  }
  return current;
}
