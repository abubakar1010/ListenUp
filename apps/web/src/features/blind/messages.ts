import { formatClock } from '../session/time';
import type { BlindAttempt } from './api';

/** Why an attempt ended, in plain words with what to do next (final UI D03, D07). */
export function endedMessage(attempt: BlindAttempt): string {
  const at = formatClock(Math.max(0, attempt.position_ms - attempt.passage_start_ms));
  const again = 'Blind needs one full listen, so you start again from 00:00.';
  switch (attempt.void_reason) {
    case 'left_page':
      return `You left the page at ${at}. ${again}`;
    case 'reload':
      return `The page reloaded at ${at}. ${again}`;
    case 'seek':
      return `Playback jumped at ${at}. Blind can't go back or skip ahead. ${again}`;
    case 'missed_heartbeat':
      return `We lost contact with your player at ${at}. ${again} Keep this screen open while you listen.`;
    case 'too_fast':
      return `Playback ran faster than real time at ${at}. ${again}`;
    case 'interrupted':
      if (attempt.resume_count > 0 && attempt.resume_stop_ms !== null) {
        const used = formatClock(Math.max(0, attempt.resume_stop_ms - attempt.passage_start_ms));
        return `Playback stopped again at ${at}. Blind can carry on once per attempt, and that was used at ${used}. That's not your fault. Start again from 00:00 when your connection is steady.`;
      }
      return `Playback stopped at ${at} for 5 seconds or more, so this attempt ended. That's not your fault. Check your headphones or connection, then start again.`;
    default:
      return again;
  }
}
