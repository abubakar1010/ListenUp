import type { components } from '../../api/schema';

type Item = Pick<components['schemas']['ContentItem'], 'status' | 'stage' | 'queue_position'>;

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  const suffixes: Record<number, string> = { 1: 'st', 2: 'nd', 3: 'rd' };
  return `${n}${suffixes[n % 10] ?? 'th'}`;
}

/**
 * A short label for a clip still being prepared (FR-CI-5, #40, #41): where it is in the
 * learner's own queue, or which step the conversion job is on. Null once it is prepared.
 */
export function stageLabel(item: Item): string | null {
  if (item.status !== 'pending' && item.status !== 'downloading') return null;
  switch (item.stage) {
    case 'queued':
      return item.queue_position ? `Queued · ${ordinal(item.queue_position)} in line` : 'Queued';
    case 'waiting':
      return 'Waiting to start';
    case 'downloading':
      return 'Downloading';
    case 'checking':
      return 'Checking the file';
    case 'converting':
      return 'Converting';
    case 'saving':
      return 'Almost ready';
    default:
      return item.status === 'downloading' ? 'Downloading' : 'Processing';
  }
}

/**
 * The same, as a sentence for the clip's own page: what is happening and that the page
 * updates by itself (NFR-USE-3).
 */
export function stageSentence(item: Item): string {
  const updates = 'This page updates by itself when the clip is ready.';
  switch (item.stage) {
    case 'queued': {
      const place = item.queue_position ? ` It is ${ordinal(item.queue_position)} in line.` : '';
      return `Waiting for your other clips: two of your clips are prepared at a time.${place} ${updates}`;
    }
    case 'waiting':
      return `Waiting to start. ${updates}`;
    case 'downloading':
      return `Downloading. ${updates}`;
    case 'checking':
      return `Checking the file. ${updates}`;
    case 'converting':
      return `Converting it for playback. ${updates}`;
    case 'saving':
      return `Almost ready: saving the playback file. ${updates}`;
    default:
      return item.status === 'downloading' ? `Downloading. ${updates}` : `Processing. ${updates}`;
  }
}
