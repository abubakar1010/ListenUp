import { useCallback, useEffect, useRef, useState } from 'react';
import { buttonClass } from '../../components/button';

type Phase = 'ready' | 'counting' | 'playing' | 'interrupted' | 'blocked' | 'ended' | 'error';

/** Playback only. Recording hooks will attach to count-in/start/end in #81. */
export function ShadowRoundPlayer({
  src,
  startMs,
  endMs,
  number,
  onEnded,
}: {
  src: string;
  startMs: number;
  endMs: number;
  number: number;
  onEnded?: () => void;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [ready, setReady] = useState(false);
  const [phase, setPhase] = useState<Phase>('ready');
  const phaseRef = useRef<Phase>('ready');
  const [count, setCount] = useState(3);
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const generation = useRef(0);
  const done = useRef(false);
  const cancelPendingPlay = useCallback(() => {
    generation.current++;
  }, []);
  const transition = useCallback((value: Phase) => {
    phaseRef.current = value;
    setPhase(value);
  }, []);
  const stop = useCallback(() => {
    cancelPendingPlay();
    clearInterval(timer.current);
    transition('interrupted');
    audio.current?.pause();
  }, [transition, cancelPendingPlay]);
  const play = useCallback(async () => {
    const element = audio.current;
    if (!element) return;
    const token = generation.current;
    element.defaultPlaybackRate = element.playbackRate = 1;
    transition('playing');
    try {
      await element.play();
    } catch {
      if (generation.current === token) transition('blocked');
    }
  }, [transition]);
  const begin = () => {
    cancelPendingPlay();
    done.current = false;
    if (audio.current) audio.current.currentTime = startMs / 1000;
    transition('counting');
    setCount(3);
    let remaining = 3;
    clearInterval(timer.current);
    timer.current = setInterval(() => {
      remaining--;
      if (remaining === 0) {
        clearInterval(timer.current);
        void play();
      } else setCount(remaining);
    }, 1000);
  };
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    const rate = () => {
      if (element.defaultPlaybackRate !== 1) element.defaultPlaybackRate = 1;
      if (element.playbackRate !== 1) element.playbackRate = 1;
    };
    const finish = () => {
      if (done.current || phaseRef.current !== 'playing') return;
      done.current = true;
      transition('ended');
      element.pause();
      element.currentTime = endMs / 1000;
      onEnded?.();
    };
    const check = () => {
      if (phaseRef.current !== 'playing') return;
      if (element.currentTime * 1000 >= endMs) finish();
      else if (element.currentTime * 1000 < startMs) element.currentTime = startMs / 1000;
    };
    const loaded = () => {
      setReady(true);
      rate();
      element.currentTime = startMs / 1000;
    };
    const pause = () => {
      if (phaseRef.current !== 'playing') return;
      if (element.currentTime * 1000 >= endMs - 50) finish();
      else stop();
    };
    const error = () => {
      stop();
      transition('error');
    };
    const nativeEnd = () => {
      if (phaseRef.current !== 'playing') return;
      if (element.currentTime * 1000 >= endMs - 50) finish();
      else error();
    };
    const hidden = () => {
      if (document.hidden) stop();
    };
    let frame = 0;
    const loop = () => {
      check();
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    element.addEventListener('loadedmetadata', loaded);
    element.addEventListener('ratechange', rate);
    element.addEventListener('timeupdate', check);
    element.addEventListener('ended', nativeEnd);
    element.addEventListener('pause', pause);
    element.addEventListener('error', error);
    document.addEventListener('visibilitychange', hidden);
    if (element.readyState >= 1) loaded();
    return () => {
      cancelPendingPlay();
      clearInterval(timer.current);
      cancelAnimationFrame(frame);
      element.removeEventListener('loadedmetadata', loaded);
      element.removeEventListener('ratechange', rate);
      element.removeEventListener('timeupdate', check);
      element.removeEventListener('ended', nativeEnd);
      element.removeEventListener('pause', pause);
      element.removeEventListener('error', error);
      document.removeEventListener('visibilitychange', hidden);
      element.pause();
    };
  }, [src, startMs, endMs, onEnded, stop, transition, cancelPendingPlay]);
  const active = phase === 'counting' || phase === 'playing';
  const message =
    phase === 'counting'
      ? `Round ${number} starts in ${count}`
      : phase === 'playing'
        ? `Round ${number} playing at original speed`
        : phase === 'ended'
          ? `Round ${number} playback ended`
          : phase === 'interrupted'
            ? 'Playback interrupted. Restart this round when ready.'
            : phase === 'blocked'
              ? 'Playback was blocked. Press Play now to continue.'
              : phase === 'error'
                ? 'Audio unavailable. Reload to try again.'
                : ready
                  ? `Round ${number} ready`
                  : 'Loading audio…';
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <audio ref={audio} src={src} preload="auto" />
      <p role="status" aria-live="polite" aria-atomic="true">
        {message}
      </p>
      <p>Original speed · 1×</p>
      <button
        type="button"
        className={buttonClass('primary', 'self-start')}
        disabled={!ready || phase === 'error' || phase === 'ended'}
        onClick={active ? stop : phase === 'blocked' ? () => void play() : begin}
      >
        {active
          ? `Stop round ${number}`
          : phase === 'blocked'
            ? 'Play now'
            : `Play round ${number}`}
      </button>
    </div>
  );
}
