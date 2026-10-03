import { describeError } from '../../components/describeError';
import type { AutosaveStatus } from './autosave';

/** "10:51" in the learner's time zone, 24-hour like the design. */
export function clockTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

/** The one-line save state, for the header and under a field (#50). */
export function saveStatusText<T>(status: AutosaveStatus<T>, noun = 'Draft'): string {
  switch (status.kind) {
    case 'saved':
      return status.at ? `${noun} saved ${clockTime(status.at)}` : `${noun} saved`;
    case 'pending':
    case 'saving':
      return 'Saving…';
    case 'offline':
      return 'Offline. Saved on this device.';
    case 'retrying':
      return 'Server busy. Saved on this device; trying again soon.';
    case 'conflict':
      return 'Changed in another tab. Not saved.';
    case 'failed':
      return `Not saved. ${describeError(status.error).detail}`;
  }
}
