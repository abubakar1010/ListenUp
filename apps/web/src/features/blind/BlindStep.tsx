import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';

import { PageLoading } from '../../app/PageLoading';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { AlertIcon } from '../../components/icons';
import type { Session } from '../session/api';
import { PracticeLayout } from '../session/PracticeLayout';
import { StepProgress } from '../session/StepProgress';
import { formatClock, formatLength } from '../session/time';
import {
  blindKey,
  sendHeartbeat,
  startAttempt,
  useBlindStep,
  voidAttempt,
  type BlindAttempt,
} from './api';
import { BlindPlayer, type PlayerStatus } from './BlindPlayer';
import { GistForm } from './GistForm';
import { BlindListen, type ListenSnapshot } from './listen';
import { endedMessage } from './messages';

const RULE = 'No pausing. Listen once, all the way through.';
const RULE_AFTER_RESUME = 'Resume used. If playback stops again, this attempt ends.';

/** Media keys and the OS's player controls must not pause or seek Blind (UI-3). */
const MEDIA_ACTIONS: MediaSessionAction[] = [
  'play',
  'pause',
  'stop',
  'seekbackward',
  'seekforward',
  'seekto',
  'previoustrack',
  'nexttrack',
];

function lockMediaKeys(): () => void {
  const session = typeof navigator !== 'undefined' ? navigator.mediaSession : undefined;
  if (!session) return () => undefined;
  const set = (handler: MediaSessionActionHandler | null) => {
    for (const action of MEDIA_ACTIONS) {
      try {
        session.setActionHandler(action, handler);
      } catch {
        // Not every browser knows every action.
      }
    }
  };
  set(() => undefined);
  return () => set(null);
}

async function keepScreenOn(): Promise<() => void> {
  try {
    const lock = await navigator.wakeLock?.request('screen');
    return () => void lock?.release().catch(() => undefined);
  } catch {
    return () => undefined;
  }
}

function useListen(listen: BlindListen | null): ListenSnapshot | null {
  return useSyncExternalStore(
    (notify) => (listen ? listen.subscribe(notify) : () => undefined),
    () => (listen ? listen.getSnapshot() : null),
  );
}

interface BlindStepProps {
  session: Session;
  /** The step progress with its "Change entry" action, shown while not listening. */
  progress: ReactNode;
}

/**
 * The Blind step (FR-BL-1 to FR-BL-4; final UI D01 to D04, D07): the rules and a
 * Start button, one locked listen, then the gist. Leaving, reloading or seeking
 * during the listen ends the attempt and says so; one interruption the learner did
 * not cause resumes on its own.
 */
export function BlindStep({ session, progress }: BlindStepProps) {
  const step = useBlindStep(session.id);
  const queryClient = useQueryClient();
  const audio = useRef<HTMLAudioElement>(null);
  const [listen, setListen] = useState<BlindListen | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const [ended, setEnded] = useState<BlindAttempt | null>(null);
  const [volume, setVolume] = useState(0.8);
  const snapshot = useListen(listen);
  const reloadChecked = useRef(false);

  const latest = step.data?.attempt ?? null;
  // Why the last attempt ended: this page's listen, a reload just voided, or the
  // newest attempt as the server has it.
  const stoppedHere = snapshot?.phase.kind === 'stopped' ? snapshot.phase.attempt : null;
  const shownEnded =
    stoppedHere ?? ended ?? (!listen && latest?.status === 'voided' ? latest : null);
  const phase = snapshot?.phase.kind;
  const listening = listen !== null && listen.inProgress;

  useEffect(() => {
    if (audio.current) audio.current.volume = volume;
  }, [volume, listen]);

  // A live attempt from before this page loaded, not yet heard to the end: the page
  // was reloaded or reopened mid-listen, so it ends (NFR-REL-3).
  useEffect(() => {
    if (reloadChecked.current || !latest || listen) return;
    reloadChecked.current = true;
    if (latest.status === 'active' && !latest.listen_complete) {
      void voidAttempt(latest.id, 'reload')
        .then((attempt) => setEnded(attempt))
        .finally(() => void queryClient.invalidateQueries({ queryKey: blindKey(session.id) }));
    }
  }, [latest, listen, queryClient, session.id]);

  // While listening: warn before unloading, end the attempt on leaving, lock media keys.
  useEffect(() => {
    if (!listen || !listening) return;
    const onHide = () => {
      if (document.visibilityState === 'hidden') listen.leave('left_page');
    };
    const onPageHide = () => listen.leave('left_page');
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('beforeunload', onBeforeUnload);
    const unlockKeys = lockMediaKeys();
    let releaseScreen: () => void = () => undefined;
    void keepScreenOn().then((release) => (releaseScreen = release));
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('beforeunload', onBeforeUnload);
      unlockKeys();
      releaseScreen();
    };
  }, [listen, listening]);

  // Leaving the screen inside the app (Back, another link) ends the listen too.
  useEffect(() => {
    if (!listen) return;
    return () => {
      listen.leave('left_page');
      listen.dispose();
    };
  }, [listen]);

  async function start() {
    if (!audio.current || starting) return;
    setStarting(true);
    setStartError(null);
    setEnded(null);
    // The previous listen (ended) lets go of the audio element first.
    listen?.leave('left_page');
    listen?.dispose();
    try {
      const started = await startAttempt(session.id);
      const controller = new BlindListen(audio.current, started, {
        heartbeat: sendHeartbeat,
        void: voidAttempt,
      });
      // When the server ends the attempt, refresh the step so it shows the reason.
      const unsubscribe = controller.subscribe(() => {
        if (controller.getSnapshot().phase.kind === 'stopped') {
          unsubscribe();
          void queryClient.invalidateQueries({ queryKey: blindKey(session.id) });
        }
      });
      controller.begin();
      reloadChecked.current = true;
      setListen(controller);
    } catch (error) {
      setStartError(error);
      void queryClient.invalidateQueries({ queryKey: blindKey(session.id) });
    } finally {
      setStarting(false);
    }
  }

  if (step.isPending) return <PageLoading />;
  if (step.isError) {
    return (
      <main className="mx-auto flex w-full max-w-content flex-col gap-4 px-4 pt-4 pb-8 md:px-6">
        <h1 className="sr-only">Blind</h1>
        <ErrorPanel error={step.error} onRetry={() => void step.refetch()} />
      </main>
    );
  }

  const { passage_start_ms: start_ms, passage_end_ms: end_ms } = step.data;
  const length = end_ms - start_ms;
  // The gist: heard to the end in this page, or an earlier listen that finished.
  const gistAttempt =
    phase === 'ended' && listen
      ? listen.attemptId
      : latest?.status === 'active' && latest.listen_complete && !listen
        ? latest.id
        : null;

  let status: PlayerStatus = 'before';
  if (gistAttempt) status = 'done';
  else if (starting || phase === 'loading') status = 'starting';
  else if (phase === 'playing') status = 'listening';
  else if (phase === 'waiting') status = 'waiting';
  else if (phase === 'resuming') status = 'resuming';
  const played = gistAttempt ? length : (snapshot?.positionMs ?? start_ms) - start_ms;
  const resumed = snapshot?.resumeStopMs != null;

  let work: ReactNode;
  if (gistAttempt) {
    work = <GistForm sessionId={session.id} attemptId={gistAttempt} />;
  } else if (snapshot && listening) {
    work = (
      <Listening
        snapshot={snapshot}
        startMs={start_ms}
        remainingMs={length - played}
        onCarryOn={() => listen?.carryOnNow()}
      />
    );
  } else if (snapshot?.phase.kind === 'failed') {
    work = <ErrorPanel error={snapshot.phase.error} onRetry={() => setListen(null)} />;
  } else {
    work = (
      <Before lengthMs={length}>
        {shownEnded && <EndedNotice attempt={shownEnded} />}
        {startError !== null && <ErrorPanel error={startError} />}
      </Before>
    );
  }

  return (
    <PracticeLayout
      heading={`Blind: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={
        listening
          ? 'Blind · listening'
          : `Passage ${formatClock(start_ms)} to ${formatClock(end_ms)}`
      }
      back={listening ? null : { to: '/library', label: 'Library' }}
      progress={listening ? <StepProgress session={session} /> : progress}
      player={
        <>
          {/* No controls and not focusable: start and volume are the only controls. */}
          <audio ref={audio} preload="auto" tabIndex={-1} aria-hidden="true" className="hidden" />
          <BlindPlayer
            status={status}
            playedMs={played}
            lengthMs={length}
            volume={volume}
            onVolume={setVolume}
            onStart={() => void start()}
          />
        </>
      }
      rule={resumed && listening ? RULE_AFTER_RESUME : RULE}
      workLabel="Blind"
    >
      {work}
    </PracticeLayout>
  );
}

function EndedNotice({ attempt }: { attempt: BlindAttempt }) {
  return (
    <div
      role="alert"
      className="flex gap-3 rounded-md border-2 border-danger bg-surface-raised p-4"
    >
      <AlertIcon className="size-5 flex-none text-danger" />
      <div className="flex flex-col gap-1">
        <h2 className="font-display text-heading">Your Blind attempt ended</h2>
        <p>{endedMessage(attempt)}</p>
        <p className="text-body-s text-ink-muted">Press Start listening when you're ready.</p>
      </div>
    </div>
  );
}

function Before({ lengthMs, children }: { lengthMs: number; children: ReactNode }) {
  return (
    <>
      {children}
      <section
        aria-labelledby="blind-before"
        className="flex flex-col gap-3 rounded-md border border-line bg-surface-raised p-4 md:p-6"
      >
        <h2 id="blind-before" className="font-display text-title">
          Before you start
        </h2>
        <ul className="flex list-disc flex-col gap-2 pl-5">
          <li>
            <b>Set your volume first.</b> Volume is the only control while you listen.
          </li>
          <li>
            You'll hear <b className="font-mono">{formatLength(lengthMs)}</b> once. You can't pause,
            go back or change the speed.
          </li>
          <li>
            Leaving the page or reloading ends this attempt, and you start again from the beginning.
            If the connection drops, or your headphones or phone pause for under 5 seconds, you can
            carry on once.
          </li>
          <li>When it ends, you write three sentences about what you heard.</li>
        </ul>
        <p className="text-body-s text-ink-muted">
          Real conversations don't stop for you. Use headphones, don't take notes, and listen for
          the main idea first.
        </p>
      </section>
    </>
  );
}

function Listening({
  snapshot,
  startMs,
  remainingMs,
  onCarryOn,
}: {
  snapshot: ListenSnapshot;
  startMs: number;
  remainingMs: number;
  onCarryOn: () => void;
}) {
  const carryOn = useRef<HTMLButtonElement>(null);
  const phase = snapshot.phase;
  const counting = phase.kind === 'resuming' && phase.secondsLeft !== null;
  useEffect(() => {
    if (counting) carryOn.current?.focus();
  }, [counting]);

  if (phase.kind === 'waiting') {
    const at = formatClock(Math.max(0, phase.stopMs - startMs));
    const from = formatClock(Math.max(0, phase.stopMs - startMs - 3_000));
    return (
      <section
        role="status"
        className="flex flex-col items-center gap-3 rounded-md border border-line bg-surface-raised p-6 text-center md:p-10"
      >
        <span className="rounded-full bg-surface-sunken px-3 py-1 text-label">Resume 1 of 1</span>
        <h2 className="font-display text-title">
          {phase.cause === 'network' ? `Connection lost at ${at}` : `Playback paused at ${at}`}
        </h2>
        <p>
          This isn't your fault, and your attempt is kept. Listening goes on by itself from{' '}
          <span className="font-mono">{from}</span>, 3 seconds before the stop.
        </p>
        <p className="text-body-s text-ink-muted">
          {phase.cause === 'network' ? 'Checking the connection…' : 'Waiting for your device…'} Keep
          this screen open. If playback stops again, this attempt ends.
        </p>
      </section>
    );
  }
  if (phase.kind === 'resuming') {
    const from = formatClock(Math.max(0, phase.fromMs - startMs));
    return (
      <section
        role="status"
        className="flex flex-col items-center gap-3 rounded-md border border-line bg-surface-raised p-6 text-center md:p-10"
      >
        <h2 className="font-display text-title">
          {phase.secondsLeft === null ? 'Getting the audio ready' : 'Ready to carry on'}
        </h2>
        <p>
          Listening goes on from <span className="font-mono">{from}</span>
          {phase.secondsLeft !== null && (
            <>
              {' '}
              in <b className="font-mono">{phase.secondsLeft}</b>
            </>
          )}
          .
        </p>
        {counting && (
          <button
            ref={carryOn}
            type="button"
            className={buttonClass('primary')}
            onClick={onCarryOn}
          >
            Carry on now
          </button>
        )}
      </section>
    );
  }
  return (
    <section
      aria-label="Time left"
      className="flex flex-col items-center gap-2 rounded-md border border-line bg-surface-raised p-10 text-center md:p-16"
    >
      <span aria-hidden="true" className="font-mono text-display font-semibold tabular-nums">
        {formatClock(Math.max(0, remainingMs))}
      </span>
      <span className="text-label text-ink-muted uppercase">left</span>
      <p>Keep listening. Don't take notes. You'll write the gist when it ends.</p>
      {snapshot.devicePauseMs !== null && (
        <p role="status" className="text-body-s text-ink-muted">
          Your device paused playback for {Math.max(1, Math.round(snapshot.devicePauseMs / 1000))}{' '}
          s. We carried on. Resume used.
        </p>
      )}
    </section>
  );
}
