import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../../api/client';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { PassagePlayerControls } from '../media/PassagePlayerControls';
import { actionFor, stepSpeed } from '../media/playerPolicy';
import { usePassagePlayer, type PassagePlayer } from '../media/usePassagePlayer';
import type { Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { STEP_RULES } from '../session/plan';
import { formatClock } from '../session/time';
import { useTranscript, type TranscriptReview } from './api';
import { currentLine } from './line';

export function TranscriptScreen({ session, progress }: { session: Session; progress: ReactNode }) {
  const transcript = useTranscript(session.id);
  if (transcript.data)
    return (
      <TranscriptWork
        key={session.id}
        session={session}
        progress={progress}
        data={transcript.data}
      />
    );
  const code = transcript.error instanceof ApiError ? transcript.error.code : null;
  const waiting = code === 'transcript_not_ready';
  const failed = code === 'transcript_failed';
  return (
    <Layout session={session} progress={progress} player={null}>
      {waiting || failed ? (
        <div className="flex flex-col items-start gap-3">
          <p role={waiting ? 'status' : 'alert'}>
            {waiting ? 'Preparing your transcript…' : 'The transcript could not be prepared.'}
          </p>
          <p>Your progress is saved. Try again to check for an updated transcript.</p>
          <button
            type="button"
            className={buttonClass('secondary')}
            onClick={() => void transcript.refetch()}
          >
            Try again
          </button>
        </div>
      ) : transcript.isError ? (
        <ErrorPanel error={transcript.error} onRetry={() => void transcript.refetch()} />
      ) : (
        <p role="status">Opening your Transcript…</p>
      )}
    </Layout>
  );
}

function Layout({
  session,
  progress,
  player,
  children,
}: {
  session: Session;
  progress: ReactNode;
  player: ReactNode;
  children: ReactNode;
}) {
  return (
    <PracticeLayout
      heading={`Transcript: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={`Passage ${formatClock(session.passage.start_ms)} to ${formatClock(session.passage.end_ms)}`}
      back={{ to: '/library', label: 'Library' }}
      progress={progress}
      player={player}
      rule={STEP_RULES.transcript}
      workLabel="Transcript"
    >
      <p className="text-body-s">Transcript can't be skipped: it shows what you missed.</p>
      {children}
    </PracticeLayout>
  );
}

function TranscriptWork({
  session,
  progress,
  data,
}: {
  session: Session;
  progress: ReactNode;
  data: TranscriptReview;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [replays, setReplays] = useState(0);
  const player = usePassagePlayer(audio, data.passage.start_ms, data.passage.end_ms);
  const line = currentLine(data.lines, data.passage.start_ms + player.positionMs);
  const jump = (absoluteMs: number) => {
    player.seek(absoluteMs - data.passage.start_ms);
    if (audio.current?.paused) player.toggle();
  };
  const replayLine = () => {
    const target = line ?? data.lines[0];
    if (target) {
      jump(target.start_ms);
      setReplays((count) => count + 1);
    }
  };
  const controls = { ...player, replays, replay: replayLine };
  usePlayerKeys(controls);
  return (
    <Layout
      session={session}
      progress={progress}
      player={
        <PassagePlayerControls
          audioRef={audio}
          player={controls}
          src={data.media_url}
          playerId="transcript"
          replayLabel="Replay line"
          replayDisabled={data.lines.length === 0}
          description={line ? `Line ${line.index + 1} of ${data.lines.length}` : 'Passage audio'}
          errorSuffix="Your progress is saved."
        />
      }
    >
      <h2 className="font-display text-heading">Listen with the transcript</h2>
      <p>Choose any word to hear it. Replay the current line as often as you like.</p>
      <details className="rounded-md border border-line p-3">
        <summary className="cursor-pointer font-bold">Keyboard shortcuts</summary>
        <p className="mt-2 text-body-s">
          Space or K: play/pause. J: back 5 seconds. R: replay line. [ and ]: speed. Tab to a word,
          then Enter or Space to jump. Use arrow keys on the seek bar.
        </p>
      </details>
      {data.lines.length === 0 ? (
        <p>No speech was found in this passage.</p>
      ) : (
        <ol aria-label="Transcript lines" className="flex flex-col gap-3">
          {data.lines.map((item) => (
            <li
              key={item.index}
              aria-current={line?.index === item.index ? 'true' : undefined}
              className={`rounded-md border-l-4 p-3 ${line?.index === item.index ? 'border-accent bg-surface-sunken' : 'border-transparent'}`}
            >
              <span className="mb-1 block text-body-s font-bold">
                Line {item.index + 1}
                {line?.index === item.index && <span> · Current line</span>}
              </span>
              <p className="text-body-l [overflow-wrap:anywhere]">
                {item.words.map((word) => (
                  <span key={word.index}>
                    <button
                      type="button"
                      aria-label={`Jump to ${word.text}`}
                      disabled={player.status !== 'ready'}
                      className="min-h-11 max-w-full rounded-sm px-1 text-left underline decoration-dotted underline-offset-4 [overflow-wrap:anywhere] hover:bg-surface-raised"
                      onClick={() => jump(word.start_ms)}
                    >
                      {word.text}
                    </button>{' '}
                  </span>
                ))}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Layout>
  );
}

function usePlayerKeys(player: PassagePlayer) {
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        event.defaultPrevented ||
        event.repeat ||
        player.status !== 'ready' ||
        (target instanceof HTMLElement &&
          target.closest('button, input, select, textarea, a, summary, [contenteditable="true"]'))
      )
        return;
      const action = actionFor(event, false);
      if (!action) return;
      event.preventDefault();
      switch (action) {
        case 'toggle':
          player.toggle();
          break;
        case 'back':
          player.back();
          break;
        case 'replay':
          player.replay();
          break;
        case 'slower':
          player.setSpeed(stepSpeed(player.speed, 1));
          break;
        case 'faster':
          player.setSpeed(stepSpeed(player.speed, -1));
          break;
      }
    };
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, [player]);
}
