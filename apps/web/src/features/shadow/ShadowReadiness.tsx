import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useConsentVersions, useGrantConsents, useMyConsents } from '../../auth/consentApi';
import { BusyButton } from '../../components/BusyButton';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { LegalText } from '../legal/LegalText';
import { TEXTS } from '../legal/texts';

/** Local signal check only: no MediaRecorder, retained samples or network audio. */
export function ShadowReadiness({ onReady }: { onReady: (ready: boolean) => void }) {
  const versions = useConsentVersions();
  const consents = useMyConsents();
  const grant = useGrantConsents();
  const version = versions.data?.voice_recording;
  const source =
    version && Object.hasOwn(TEXTS.voice_recording, version)
      ? TEXTS.voice_recording[version]
      : undefined;
  const [agreedVersion, setAgreedVersion] = useState<string>();
  const consent =
    !!source &&
    !!version &&
    !versions.isError &&
    !consents.isError &&
    !!consents.data?.consents.some(
      (c) => c.kind === 'voice_recording' && c.version === version && c.withdrawn_at === null,
    );
  const [status, setStatus] = useState('Check your microphone, then speak a short sentence.');
  const [checking, setChecking] = useState(false);
  const [signal, setSignal] = useState(false);
  const [level, setLevel] = useState(0);
  const release = useRef<() => void>(() => {});
  const generation = useRef(0);
  const checkButton = useRef<HTMLButtonElement>(null);
  const acceptedNotice = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (consent && grant.isSuccess) acceptedNotice.current?.focus();
  }, [consent, grant.isSuccess]);

  useEffect(() => {
    onReady(signal && consent);
  }, [signal, consent, onReady]);

  useEffect(() => {
    function stop() {
      generation.current++;
      release.current();
      setSignal(false);
      setChecking(false);
      setLevel(0);
    }
    function hidden() {
      if (document.hidden) {
        stop();
        setStatus('Microphone check stopped. Check again when ready.');
      }
    }
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', stop);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', hidden);
      window.removeEventListener('pagehide', stop);
    };
  }, []);

  async function check() {
    release.current();
    const token = ++generation.current;
    setChecking(true);
    setSignal(false);
    setLevel(0);
    setStatus('Allow microphone access, then speak a short sentence.');
    let stream: MediaStream | undefined;
    let context: AudioContext | undefined;
    let timer: ReturnType<typeof setInterval> | undefined;
    const cleanup = () => {
      clearInterval(timer);
      stream?.getTracks().forEach((track) => track.stop());
      if (context) void context.close().catch(() => {});
    };
    release.current = cleanup;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !globalThis.AudioContext) {
        throw new DOMException('Unavailable', 'NotSupportedError');
      }
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation.current !== token) {
        cleanup();
        return;
      }
      if (!stream.getAudioTracks().some((track) => track.readyState === 'live')) {
        throw new DOMException('No microphone', 'NotFoundError');
      }
      context = new AudioContext();
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(analyser);
      await context.resume();
      if (generation.current !== token) {
        cleanup();
        return;
      }
      const samples = new Float32Array(analyser.fftSize);
      let heard = 0;
      const started = performance.now();
      const lostInput = () => {
        if (generation.current !== token) return;
        generation.current++;
        cleanup();
        setSignal(false);
        setChecking(false);
        setLevel(0);
        setStatus('Microphone disconnected or muted. Connect or unmute it and check again.');
      };
      stream.getAudioTracks().forEach((track) => {
        track.addEventListener('ended', lostInput);
        track.addEventListener('mute', lostInput);
      });
      timer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(
          samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length,
        );
        setLevel(Math.min(100, Math.round(rms * 500)));
        // Count speech across pauses within the bounded check window.
        if (rms >= 0.01 && rms < 0.95) heard++;
        if (heard >= 3) {
          setSignal(true);
          setChecking(false);
          setStatus('Microphone ready. Sound detected.');
          // Keep only the live track for disconnect detection; sampling is finished.
          clearInterval(timer);
          if (context) void context.close().catch(() => {});
          context = undefined;
        } else if (performance.now() - started >= 10000) {
          cleanup();
          setChecking(false);
          setStatus(
            'No clear sound detected. Check mute and input volume, move closer, and try again.',
          );
        }
      }, 100);
    } catch (error) {
      cleanup();
      if (generation.current !== token) return;
      setChecking(false);
      const name = error instanceof Error || error instanceof DOMException ? error.name : '';
      setStatus(
        name === 'NotAllowedError' || name === 'SecurityError'
          ? 'Microphone access was denied. Allow it in your browser site settings and operating system privacy settings, then try again.'
          : name === 'NotFoundError'
            ? 'Connect a microphone or select an audio input in your system settings, then try again.'
            : name === 'NotReadableError' || name === 'AbortError'
              ? 'Close other apps using the microphone, check your device connection, then try again.'
              : 'Microphone checking is unavailable. Use a supported browser over HTTPS, or use the confirmed Skip Shadow action.',
      );
    }
  }

  return (
    <section aria-label="Microphone and voice consent" className="flex flex-col gap-4">
      <h3 className="font-bold">Before your first round</h3>
      <p>Use headphones so the original audio does not leak into your microphone.</p>
      <p>This check only measures sound locally. It does not record or upload your voice.</p>
      <BusyButton
        ref={checkButton}
        type="button"
        className={buttonClass('secondary')}
        busy={checking}
        onClick={() => void check()}
      >
        Check microphone
      </BusyButton>
      {checking && (
        <button
          type="button"
          className={buttonClass('secondary')}
          onClick={() => {
            generation.current++;
            release.current();
            setChecking(false);
            setSignal(false);
            setLevel(0);
            setStatus('Microphone check stopped. Check again when ready.');
            checkButton.current?.focus();
          }}
        >
          Cancel microphone check
        </button>
      )}
      <meter aria-label="Microphone level" min={0} max={100} value={level} />
      <p role="status">{status}</p>
      <p>
        If you cannot use a microphone or do not agree, use Skip Shadow and confirm your choice.
      </p>
      {versions.isError ? (
        <ErrorPanel error={versions.error} onRetry={() => void versions.refetch()} />
      ) : !version ? (
        <p role="status">Loading voice consent…</p>
      ) : !source ? (
        <p>The current voice consent text is unavailable. Try again later or skip Shadow.</p>
      ) : (
        <>
          <p>Voice recording consent — version {version}</p>
          <LegalText source={source} headingOffset={2} />
          {consents.isError ? (
            <ErrorPanel error={consents.error} onRetry={() => void consents.refetch()} />
          ) : consents.isPending ? (
            <p role="status">Loading your consent…</p>
          ) : consent ? (
            <p ref={acceptedNotice} tabIndex={-1} role="status">
              You agreed to this version.{' '}
              <Link to="/settings" className="text-accent underline">
                Manage or withdraw consent
              </Link>
              .
            </p>
          ) : (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={agreedVersion === version}
                  onChange={(e) => setAgreedVersion(e.target.checked ? version : undefined)}
                />{' '}
                I agree to this version of voice recording consent.
              </label>
              <BusyButton
                type="button"
                className={buttonClass('primary')}
                busy={grant.isPending}
                aria-disabled={agreedVersion !== version || undefined}
                onClick={() => {
                  if (agreedVersion === version)
                    grant.mutate([{ kind: 'voice_recording', version }]);
                }}
              >
                Agree to voice recording
              </BusyButton>
            </>
          )}
        </>
      )}
      {grant.isError && <ErrorPanel error={grant.error} onRetry={() => void versions.refetch()} />}
    </section>
  );
}
