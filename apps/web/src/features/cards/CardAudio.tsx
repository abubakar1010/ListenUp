import { useEffect, useRef, useState } from 'react';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useRetryCardAudio, type Card } from './api';

export function CardAudio({ card }: { card: Card }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const retry = useRetryCardAudio(card.session_id);
  const reason = `card-audio-${card.id}`;
  const ready = card.audio_status === 'ready';
  useEffect(() => {
    const element = audio.current;
    return () => {
      element?.pause();
    };
  }, []);
  async function toggle() {
    if (!ready || !audio.current) return;
    if (playing) {
      audio.current.pause();
      return;
    }
    setFailed(false);
    setLoading(true);
    audio.current.src = `/api/v1/cards/${encodeURIComponent(card.id)}/audio`;
    try {
      await audio.current.play();
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="flex flex-col gap-2">
      <audio
        ref={audio}
        preload="none"
        onPlaying={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => {
          setFailed(true);
          setPlaying(false);
          setLoading(false);
        }}
      />
      <button
        type="button"
        className={buttonClass('quiet', 'self-start')}
        aria-disabled={!ready || loading}
        aria-busy={loading}
        aria-describedby={!ready ? reason : undefined}
        onClick={() => {
          if (!loading) void toggle();
        }}
      >
        {playing ? 'Pause' : 'Play'} audio: {card.written_form}
      </button>
      <p id={reason} role="status" className={ready ? 'sr-only' : undefined}>
        {ready
          ? `Audio ready: ${card.written_form}`
          : card.audio_status === 'pending'
            ? 'Preparing audio…'
            : card.audio_status === 'failed'
              ? 'Audio preparation failed. You can try again.'
              : 'Audio is unavailable for this older card.'}
      </p>
      {card.audio_status === 'failed' && (
        <button
          type="button"
          className={buttonClass('quiet', 'self-start')}
          aria-disabled={retry.isPending}
          aria-busy={retry.isPending}
          onClick={() => {
            if (!retry.isPending) retry.mutate(card.id);
          }}
        >
          Retry audio: {card.written_form}
        </button>
      )}
      {retry.isError && <ErrorPanel error={retry.error} />}
      {failed && <p role="alert">Audio could not play. Press Play audio to try again.</p>}
    </div>
  );
}
