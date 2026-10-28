import { useCallback, useEffect, useRef } from 'react';

/** Opus in WebM first; Safari has AAC in MP4 (FR-SH-5). */
const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

export function pickRecordingType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  return TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** The base type the API accepts, without codec parameters. */
export const baseType = (type: string) => type.split(';')[0];

export interface Recording {
  blob: Blob;
  mime: string;
}

/**
 * One MediaRecorder at a time: `begin` at the count-in, `finish` at the end of the
 * segment (resolves the recording, or null when none was made), `cancel` on any stop.
 */
export function useRoundRecorder() {
  const recorder = useRef<MediaRecorder | undefined>(undefined);
  const stream = useRef<MediaStream | undefined>(undefined);
  const chunks = useRef<Blob[]>([]);
  const generation = useRef(0);
  const release = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = undefined;
    recorder.current = undefined;
  }, []);
  const cancel = useCallback(() => {
    generation.current++;
    const active = recorder.current;
    recorder.current = undefined;
    if (active?.state === 'recording') {
      // Nothing is kept: the round was interrupted.
      chunks.current = [];
      active.stop();
    }
    release();
  }, [release]);
  const begin = useCallback(async (): Promise<'recording' | 'unavailable' | 'cancelled'> => {
    cancel();
    const type = pickRecordingType();
    if (!type || !navigator.mediaDevices?.getUserMedia) return 'unavailable';
    const token = generation.current;
    try {
      const input = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation.current !== token) {
        input.getTracks().forEach((track) => track.stop());
        return 'cancelled';
      }
      stream.current = input;
      chunks.current = [];
      const active = new MediaRecorder(input, { mimeType: type });
      active.addEventListener('dataavailable', (event) => {
        if (event.data.size > 0) chunks.current.push(event.data);
      });
      recorder.current = active;
      active.start();
      return 'recording';
    } catch {
      release();
      return 'unavailable';
    }
  }, [cancel, release]);
  const finish = useCallback((): Promise<Recording | null> => {
    // A microphone still opening must not start recording after the round ended.
    generation.current++;
    const active = recorder.current;
    if (!active || active.state !== 'recording') {
      release();
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      active.addEventListener('stop', () => {
        const mime = baseType(active.mimeType);
        const blob = new Blob(chunks.current, { type: mime });
        chunks.current = [];
        release();
        resolve(blob.size > 0 ? { blob, mime } : null);
      });
      active.stop();
    });
  }, [release]);
  useEffect(() => cancel, [cancel]);
  return { begin, finish, cancel };
}
