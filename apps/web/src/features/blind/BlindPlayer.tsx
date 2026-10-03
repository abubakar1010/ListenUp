import { buttonClass } from '../../components/button';
import { CheckIcon, LockIcon } from '../../components/icons';
import { formatClock, spokenLength } from '../session/time';

export type PlayerStatus = 'before' | 'starting' | 'listening' | 'waiting' | 'resuming' | 'done';

interface BlindPlayerProps {
  status: PlayerStatus;
  /** Played time into the passage and the passage's length, in ms. */
  playedMs: number;
  lengthMs: number;
  volume: number;
  onVolume: (volume: number) => void;
  onStart: () => void;
}

const STATUS_TEXT: Record<Exclude<PlayerStatus, 'before'>, string> = {
  starting: 'Starting',
  listening: 'Listening',
  waiting: 'Waiting for connection',
  resuming: 'Carrying on soon',
  done: 'Listen complete',
};

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="size-3.5 flex-none animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none"
    />
  );
}

/**
 * Blind's player (FR-BL-1, UI-3; final UI D01, D02, D07): Start once, then only
 * volume. Pause, seek, rewind and speed are not rendered; the lock pill names them.
 * The track shows progress but has no thumb and cannot be focused.
 */
export function BlindPlayer({
  status,
  playedMs,
  lengthMs,
  volume,
  onVolume,
  onStart,
}: BlindPlayerProps) {
  const played = Math.min(Math.max(0, playedMs), lengthMs);
  const percent = lengthMs > 0 ? (played / lengthMs) * 100 : 0;
  return (
    <div
      aria-label="Blind player"
      role="group"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface-raised p-3 md:p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        {status === 'before' ? (
          <button
            type="button"
            className={buttonClass('primary', 'min-h-13 px-5 font-display text-heading')}
            onClick={onStart}
          >
            <svg viewBox="0 0 16 16" className="size-5" aria-hidden="true" fill="currentColor">
              <path d="M5 3l9 5-9 5z" />
            </svg>
            Start listening
          </button>
        ) : (
          <span className="flex min-h-13 items-center gap-2 px-2 font-bold">
            {status === 'done' ? (
              <CheckIcon className="size-5 text-success" />
            ) : status === 'listening' ? (
              <span aria-hidden="true" className="size-2.5 rounded-full bg-accent" />
            ) : (
              <Spinner />
            )}
            {STATUS_TEXT[status]}
          </span>
        )}
        <span className="font-mono text-body font-medium tabular-nums">
          {formatClock(played)} / {formatClock(lengthMs)}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-3 py-1 text-body-s font-bold">
          <LockIcon className="size-4" />
          {status === 'done'
            ? 'Blind plays once. No replay.'
            : status === 'before'
              ? 'Pause, seek and speed are off'
              : 'No pausing'}
        </span>
        <span className="flex-1" />
        {status !== 'done' && (
          <label className="flex items-center gap-2">
            <svg
              viewBox="0 0 16 16"
              className="size-5"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path d="M2 6h3l3-3v10l-3-3H2z" />
              <path d="M11 5.5a3.5 3.5 0 0 1 0 5" />
            </svg>
            <span className="sr-only">Volume</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round(volume * 100)}
              onChange={(event) => onVolume(Number(event.target.value) / 100)}
              className="w-28 accent-accent"
            />
          </label>
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Playback progress"
        aria-valuemin={0}
        aria-valuemax={Math.round(lengthMs / 1000)}
        aria-valuenow={Math.round(played / 1000)}
        aria-valuetext={`${spokenLength(played)} of ${spokenLength(lengthMs)}`}
        className="h-2 overflow-hidden rounded-full bg-[repeating-linear-gradient(135deg,var(--color-line)_0_4px,transparent_4px_8px)]"
      >
        <span className="block h-full bg-accent" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
