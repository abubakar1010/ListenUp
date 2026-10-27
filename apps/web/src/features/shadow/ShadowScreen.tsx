import { useEffect, useRef, useState, type ReactNode } from 'react';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useContent } from '../content/useContent';
import { ShadowRounds } from './ShadowRounds';
import { usePassagePlayer } from '../media/usePassagePlayer';
import type { Session } from '../session/api';
import type { Handle, Range } from '../session/passage';
import { PracticeLayout } from '../session/PracticeLayout';
import { formatClock } from '../session/time';
import { usePeaks } from '../session/usePeaks';
import { Waveform } from '../session/Waveform';
import { useRounds, useSaveSegment, useSegment, type Segment } from './api';

/** Shadow uses the shared keyboard/pointer waveform with its own mode bounds. */
function bounds(range: Range, handle: Handle, duration: number) {
  return handle === 'start'
    ? { min: Math.max(0, range.endMs - 90_000), max: range.endMs - 60_000 }
    : { min: range.startMs + 60_000, max: Math.min(duration, range.startMs + 90_000) };
}

export function ShadowScreen({
  session,
  progress,
  skip,
}: {
  session: Session;
  progress: ReactNode;
  skip?: ReactNode;
}) {
  const segment = useSegment(session.id);
  const rounds = useRounds(session.id);
  const selection = rounds.data?.current ? rounds.data.segment : segment.data;
  const [selectionPending, setSelectionPending] = useState(false);
  const [status, setStatus] = useState('');
  return (
    <PracticeLayout
      heading={`Shadow: ${session.content_title}`}
      clipTitle={session.content_title}
      progress={progress}
      back={{ to: '/library', label: 'Library' }}
      player={null}
      rule="Three rounds at original speed. Transcript in round 1 only; short count-in before each playback."
      workLabel="Shadow segment"
    >
      <p role="status" aria-atomic="true">
        {!selection && !segment.isError ? 'Preparing your segment…' : status}
      </p>
      {selection ? (
        <SegmentEditor
          key={`${session.id}:${selection.locked_at}`}
          session={session}
          initial={selection}
          onPending={setSelectionPending}
          onStatus={setStatus}
        />
      ) : segment.isError ? (
        <ErrorPanel error={segment.error} onRetry={() => void segment.refetch()} />
      ) : null}
      {selection && (
        <ShadowRounds
          key={session.id}
          sessionId={session.id}
          contentId={session.content_id}
          selectionPending={selectionPending}
          onStatus={setStatus}
        />
      )}
      {skip}
    </PracticeLayout>
  );
}

function SegmentEditor({
  session,
  initial,
  onPending,
  onStatus,
}: {
  session: Session;
  initial: Segment;
  onPending: (value: boolean) => void;
  onStatus: (message: string) => void;
}) {
  const offset = session.passage.start_ms;
  const duration = session.passage.end_ms - offset;
  const [range, setRange] = useState<Range>({
    startMs: initial.start_ms - offset,
    endMs: initial.end_ms - offset,
  });
  const [dirty, setDirty] = useState(false);
  const save = useSaveSegment(session.id);
  const clip = useContent(session.content_id);
  const peaks = usePeaks(clip.data?.peaks_url ?? null);
  useEffect(() => {
    onPending(dirty || save.isPending);
  }, [dirty, save.isPending, onPending]);
  const locked = initial.locked_at !== null || save.data?.locked_at != null;
  const fixed = duration <= 60_000;
  // Peaks cover the media; this waveform displays only the selected passage.
  const cropped = peaks.data
    ? {
        ...peaks.data,
        values: peaks.data.values.slice(
          Math.floor((offset / 1000) * peaks.data.perSecond),
          Math.ceil((session.passage.end_ms / 1000) * peaks.data.perSecond),
        ),
      }
    : null;
  return (
    <div className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6">
      <h2 className="font-display text-heading">Your Shadow segment</h2>
      <p>
        {initial.chosen_by === 'system'
          ? 'Suggested around your densest marks.'
          : 'Your saved selection.'}{' '}
        {save.data?.mark_count ?? initial.mark_count} marks in the saved segment.
      </p>
      <p>
        Segment {formatClock(offset + range.startMs)} to {formatClock(offset + range.endMs)} ·{' '}
        {(range.endMs - range.startMs) / 1000} seconds
      </p>
      {locked ? (
        <p>Segment locked. Round 1 has started.</p>
      ) : fixed ? (
        <p>This passage is 60 seconds or shorter, so Shadow uses the whole passage.</p>
      ) : (
        <>
          <p>
            Tab to a handle. Use arrow keys for 1 second, Shift + arrows for 5 seconds, or Home and
            End.
          </p>
          <Waveform
            durationMs={duration}
            range={range}
            peaks={cropped}
            boundsFor={bounds}
            label="Segment"
            onChange={(next) => {
              if (save.isPending) return;
              setRange(next);
              onStatus('Segment selection changed.');
              setDirty(true);
              save.reset();
            }}
          />
          <button
            type="button"
            className={buttonClass('primary', 'self-start')}
            disabled={save.isPending}
            onClick={() =>
              save.mutate(
                { start_ms: offset + range.startMs, end_ms: offset + range.endMs },
                {
                  onSuccess: () => {
                    setDirty(false);
                    onStatus('Segment saved.');
                  },
                },
              )
            }
          >
            {save.isPending ? 'Saving…' : 'Save segment'}
          </button>
        </>
      )}
      {save.isError && <ErrorPanel error={save.error} />}
      {clip.isError && <ErrorPanel error={clip.error} onRetry={() => void clip.refetch()} />}
      {!locked && clip.data?.media_url && (
        <SegmentPreview
          key={`${range.startMs}:${range.endMs}`}
          startMs={offset + range.startMs}
          endMs={offset + range.endMs}
          src={clip.data.media_url}
        />
      )}
    </div>
  );
}

/** Mount only once the media URL exists; each new selection starts its own preview. */
function SegmentPreview({ startMs, endMs, src }: { startMs: number; endMs: number; src: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const player = usePassagePlayer(audioRef, startMs, endMs);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const rate = () => {
      if (audio.defaultPlaybackRate !== 1) audio.defaultPlaybackRate = 1;
      if (audio.playbackRate !== 1) audio.playbackRate = 1;
    };
    rate();
    audio.addEventListener('ratechange', rate);
    return () => {
      audio.removeEventListener('ratechange', rate);
      audio.pause();
    };
  }, []);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <audio ref={audioRef} src={src} preload="auto" />
      <p>Preview your selected segment · Original speed · 1×</p>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          className={buttonClass('secondary')}
          disabled={player.status !== 'ready'}
          onClick={player.toggle}
        >
          {player.playing ? 'Pause' : 'Play'}
        </button>
        <button
          type="button"
          className={buttonClass('secondary')}
          disabled={player.status !== 'ready'}
          onClick={() => {
            player.seek(0);
            player.replay();
          }}
        >
          Replay selected segment
        </button>
      </div>
      <label className="flex flex-col gap-2">
        Seek
        <input
          type="range"
          className="h-11 w-full cursor-pointer accent-[var(--color-accent)] md:h-6"
          disabled={player.status !== 'ready'}
          min={0}
          max={player.durationMs}
          value={player.positionMs}
          onChange={(e) => player.seek(Number(e.target.value))}
        />
      </label>
      {player.status === 'error' && <p role="alert">Audio unavailable. Your segment is kept.</p>}
    </div>
  );
}
