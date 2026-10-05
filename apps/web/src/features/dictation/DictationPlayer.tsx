import { SPEEDS, clock, segmentAt, speedLabel, spokenTime, type Speed } from './policy';
import type { PassagePlayer } from './usePassagePlayer';

const icon = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
  className: 'size-5',
} as const;

const BUTTON =
  'inline-flex size-11 flex-none items-center justify-center rounded-full border border-line-strong bg-surface-raised text-ink hover:border-ink disabled:cursor-not-allowed disabled:text-ink-muted';
const MAIN_BUTTON =
  'inline-flex size-14 flex-none items-center justify-center rounded-full border border-transparent bg-accent text-on-accent hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted';

/**
 * The Dictation player (#51; design E01): back 5 s, play or pause, replay the segment,
 * the speed, and a seek bar over the passage only. It shows no text of any kind
 * (FR-DI-3, FR-TX-5). Keyboard shortcuts are handled by the screen.
 */
export function DictationPlayer({
  audioRef,
  player,
  src,
}: {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  player: PassagePlayer;
  src: string;
}) {
  const { positionMs, durationMs, status } = player;
  const segment = segmentAt(positionMs, durationMs);
  const disabled = status !== 'ready';
  return (
    <div className="flex flex-col gap-3 rounded-md border border-line bg-surface-raised p-3 md:p-4">
      <audio ref={audioRef} src={src} preload="auto" className="hidden" />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={BUTTON}
          aria-label="Back 5 seconds"
          title="Back 5 s (J)"
          disabled={disabled}
          onClick={player.back}
        >
          <svg {...icon}>
            <path d="M8 4L4 8l4 4M13 4L9 8l4 4" />
          </svg>
        </button>
        <button
          type="button"
          className={MAIN_BUTTON}
          aria-label={player.playing ? 'Pause' : 'Play'}
          title={
            player.playing
              ? 'Pause (Space, or Esc while typing)'
              : 'Play (Space, or Esc while typing)'
          }
          disabled={disabled}
          onClick={player.toggle}
        >
          {player.playing ? (
            <svg {...icon} fill="currentColor">
              <path d="M4 3h3v10H4zM9 3h3v10H9z" />
            </svg>
          ) : (
            <svg {...icon} fill="currentColor">
              <path d="M5 3l8 5-8 5z" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className={BUTTON}
          aria-label="Replay segment"
          title="Replay segment (R)"
          disabled={disabled}
          onClick={player.replay}
        >
          <svg {...icon}>
            <path d="M3 8a5 5 0 1 0 1.5-3.5" />
            <path d="M3 2.5v3h3" />
          </svg>
        </button>
        <span className="flex min-w-0 flex-col">
          <span className="font-mono text-mono">
            {clock(positionMs)} / {clock(durationMs)}
          </span>
          <span className="text-body-s text-ink-muted">
            Segment {segment.number} of {segment.count} ·{' '}
            <span className="font-mono">{clock(segment.startMs)}</span> to{' '}
            <span className="font-mono">{clock(segment.endMs)}</span>
          </span>
        </span>
        <span className="flex-1" />
        <span className="flex items-center gap-3">
          <span className="text-body-s text-ink-muted">
            <b className="font-mono text-ink">{player.replays}</b>{' '}
            {player.replays === 1 ? 'replay' : 'replays'}
          </span>
          <label className="sr-only" htmlFor="dictation-speed">
            Speed
          </label>
          <select
            id="dictation-speed"
            className="min-h-11 rounded-md border border-line-strong bg-surface-raised px-2 font-mono text-mono"
            value={player.speed}
            onChange={(event) => player.setSpeed(Number(event.target.value) as Speed)}
          >
            {SPEEDS.map((speed) => (
              <option key={speed} value={speed}>
                {speedLabel(speed)}
              </option>
            ))}
          </select>
        </span>
      </div>
      <input
        type="range"
        aria-label="Seek"
        className="w-full accent-[var(--color-accent)]"
        min={0}
        max={durationMs}
        step={1000}
        value={positionMs}
        aria-valuetext={`${spokenTime(positionMs)} of ${spokenTime(durationMs)}`}
        disabled={disabled}
        onChange={(event) => player.seek(Number(event.target.value))}
      />
      {status === 'loading' && (
        <p role="status" className="text-body-s text-ink-muted">
          Loading the audio…
        </p>
      )}
      {status === 'error' && (
        <p role="alert" className="text-body-s font-bold text-danger">
          The audio could not load. Check your connection, then reload the page. Your text is kept.
        </p>
      )}
    </div>
  );
}
