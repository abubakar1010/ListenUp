import { useCallback, useEffect, useRef, useState } from 'react';

import { BACK_MS, DEFAULT_SPEED, clamp, replayStart, type Speed } from './policy';

export type PlayerStatus = 'loading' | 'ready' | 'error';

export interface PassagePlayer {
  status: PlayerStatus;
  playing: boolean;
  /** Milliseconds from the passage's start. */
  positionMs: number;
  durationMs: number;
  speed: Speed;
  replays: number;
  toggle: () => void;
  back: () => void;
  replay: () => void;
  seek: (positionMs: number) => void;
  setSpeed: (speed: Speed) => void;
}

/**
 * Plays one passage of a clip and never anything outside it (FR-DI-1): positions are
 * relative to the passage, every seek is clamped to it, and playback stops at its
 * end, checked on every animation frame while playing so it stops on time (NFR-PERF-4).
 * Replays are unlimited and counted (FR-DI-2, design E01).
 */
export function usePassagePlayer(
  audioRef: React.RefObject<HTMLAudioElement | null>,
  startMs: number,
  endMs: number,
): PassagePlayer {
  const durationMs = endMs - startMs;
  const [status, setStatus] = useState<PlayerStatus>('loading');
  const [playing, setPlaying] = useState(false);
  const [positionMs, setPositionMs] = useState(0);
  const [speed, setSpeedState] = useState<Speed>(DEFAULT_SPEED);
  const [replays, setReplays] = useState(0);
  const position = useRef(0);

  const moveTo = useCallback(
    (ms: number) => {
      const next = clamp(ms, durationMs);
      position.current = next;
      setPositionMs(next);
      const audio = audioRef.current;
      if (audio) audio.currentTime = (startMs + next) / 1000;
    },
    [audioRef, durationMs, startMs],
  );

  // Follow the element: keep it inside the passage and report where it is.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    let frame = 0;
    const check = () => {
      const at = audio.currentTime * 1000 - startMs;
      if (at >= durationMs) {
        audio.pause();
        moveTo(durationMs);
      } else if (at < -250) {
        moveTo(0);
      } else {
        position.current = clamp(at, durationMs);
        setPositionMs(position.current);
      }
    };
    const loop = () => {
      check();
      if (!audio.paused) frame = requestAnimationFrame(loop);
    };
    const onLoaded = () => {
      audio.currentTime = (startMs + position.current) / 1000;
      setStatus('ready');
    };
    const onPlay = () => {
      setPlaying(true);
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(loop);
    };
    const onPause = () => {
      setPlaying(false);
      cancelAnimationFrame(frame);
    };
    const onError = () => setStatus('error');
    audio.addEventListener('loadedmetadata', onLoaded);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('timeupdate', check);
    audio.addEventListener('error', onError);
    if (audio.readyState >= 1) onLoaded();
    return () => {
      cancelAnimationFrame(frame);
      audio.removeEventListener('loadedmetadata', onLoaded);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('timeupdate', check);
      audio.removeEventListener('error', onError);
    };
  }, [audioRef, durationMs, moveTo, startMs]);

  const play = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (position.current >= durationMs) moveTo(0);
    audio.play()?.catch(() => setPlaying(false));
  }, [audioRef, durationMs, moveTo]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) play();
    else audio.pause();
  }, [audioRef, play]);

  const back = useCallback(() => moveTo(position.current - BACK_MS), [moveTo]);

  const replay = useCallback(() => {
    moveTo(replayStart(position.current, durationMs));
    setReplays((count) => count + 1);
    play();
  }, [durationMs, moveTo, play]);

  const setSpeed = useCallback(
    (next: Speed) => {
      setSpeedState(next);
      const audio = audioRef.current;
      if (audio) {
        audio.defaultPlaybackRate = next;
        audio.playbackRate = next;
        audio.preservesPitch = true;
      }
    },
    [audioRef],
  );

  return {
    status,
    playing,
    positionMs,
    durationMs,
    speed,
    replays,
    toggle,
    back,
    replay,
    seek: moveTo,
    setSpeed,
  };
}
