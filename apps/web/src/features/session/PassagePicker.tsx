import { useEffect, useRef, useState, type RefObject } from 'react';

import { buttonClass } from '../../components/button';
import {
  MAX_PASSAGE_MS,
  MIN_PASSAGE_MS,
  previewWindow,
  wholeFits,
  type Handle,
  type Peaks,
  type Range,
} from './passage';
import { rangeOf, textOf, type PassageAction, type PassageState } from './passageState';
import { formatClock, formatLength, spokenLength } from './time';
import { Waveform } from './Waveform';

interface PassagePickerProps {
  durationMs: number;
  state: PassageState;
  /** The suggested part while the learner has not chosen one (2:30 from the first speech). */
  base: Range;
  dispatch: (action: PassageAction) => void;
  peaks: Peaks | null;
  peaksFailed: boolean;
  /** Where "Hear start" and "Hear end" play from (the API path that redirects to storage). */
  mediaUrl: string | null;
}

/** How long the length announcement waits for the learner to stop moving a handle (B04). */
const ANNOUNCE_DELAY_MS = 1000;

/**
 * The part of the clip to practise, 30 s to 15 min (C2, FR-CI-4, screen B04): the whole
 * clip, or a part chosen on the waveform with two handles or typed as mm:ss, with a short
 * check around each cut that keeps the first full listen fresh for Blind (UX-11).
 */
export function PassagePicker({
  durationMs,
  state,
  base,
  dispatch,
  peaks,
  peaksFailed,
  mediaUrl,
}: PassagePickerProps) {
  const wholeAllowed = wholeFits(durationMs);
  const range = rangeOf(state, base);
  const lengthMs = state.mode === 'whole' ? durationMs : range.endMs - range.startMs;
  const announced = useDebounced(`${spokenLength(lengthMs)} selected`, ANNOUNCE_DELAY_MS);
  const audioRef = useRef<HTMLAudioElement>(null);
  const preview = usePreview(audioRef, durationMs);

  return (
    <div className="flex flex-col gap-4">
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="sr-only">Passage</legend>
        <label
          className={`flex gap-3 rounded-md border-2 p-4 ${
            state.mode === 'whole'
              ? 'border-accent bg-accent-soft'
              : 'border-line bg-surface-raised'
          } ${wholeAllowed ? 'cursor-pointer' : 'cursor-not-allowed bg-surface-sunken'}`}
        >
          <input
            type="radio"
            name="passage-mode"
            className="mt-1 size-5 flex-none accent-accent"
            checked={state.mode === 'whole'}
            aria-disabled={wholeAllowed ? undefined : true}
            aria-describedby="passage-whole-note"
            onChange={() => wholeAllowed && dispatch({ type: 'mode', mode: 'whole' })}
          />
          <span className="flex flex-col gap-1">
            <b>
              Whole clip · <span className="font-mono">{formatClock(durationMs)}</span>
            </b>
            <span id="passage-whole-note" className="text-body-s text-ink-muted">
              {wholeNote(durationMs)}
            </span>
          </span>
        </label>
        <label
          className={`flex cursor-pointer gap-3 rounded-md border-2 p-4 ${
            state.mode === 'part' ? 'border-accent bg-accent-soft' : 'border-line bg-surface-raised'
          }`}
        >
          <input
            type="radio"
            name="passage-mode"
            className="mt-1 size-5 flex-none accent-accent"
            checked={state.mode === 'part'}
            onChange={() => dispatch({ type: 'mode', mode: 'part' })}
          />
          <span className="flex flex-col gap-1">
            <b>A part of it</b>
            <span className="text-body-s text-ink-muted">Recommended: 2 to 3 minutes.</span>
          </span>
        </label>
      </fieldset>

      {state.mode === 'part' && (
        <section
          aria-labelledby="passage-part-heading"
          className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 id="passage-part-heading" className="text-heading-compact md:text-heading">
              Drag the edges, or type the times
            </h3>
            <p className="rounded-full bg-surface-sunken px-2 py-1 text-label font-bold">
              <span className="font-mono">{formatLength(lengthMs)}</span> long
            </p>
          </div>

          <div className="flex flex-col gap-1">
            <Waveform
              durationMs={durationMs}
              range={range}
              peaks={peaks}
              onChange={(next) => dispatch({ type: 'set', range: next })}
            />
            <div
              aria-hidden="true"
              className="flex justify-between px-2 font-mono text-body-s text-ink-muted"
            >
              <span>{formatClock(0)}</span>
              <span>{formatClock(durationMs / 2)}</span>
              <span>{formatClock(durationMs)}</span>
            </div>
          </div>
          {peaksFailed && (
            <p className="text-body-s text-ink-muted">
              The waveform could not be loaded. You can still move the edges or type the times.
            </p>
          )}

          <div className="grid grid-cols-2 items-start gap-3 sm:flex sm:flex-wrap sm:items-end">
            <TimeField
              handle="start"
              durationMs={durationMs}
              state={state}
              base={base}
              dispatch={dispatch}
            />
            <TimeField
              handle="end"
              durationMs={durationMs}
              state={state}
              base={base}
              dispatch={dispatch}
            />
            <button
              type="button"
              className={buttonClass('secondary', 'px-3')}
              disabled={!mediaUrl}
              onClick={() => preview.hear(range.startMs)}
            >
              <PlayIcon />
              Hear start
            </button>
            <button
              type="button"
              className={buttonClass('secondary', 'px-3')}
              disabled={!mediaUrl}
              onClick={() => preview.hear(range.endMs)}
            >
              <PlayIcon />
              Hear end
            </button>
          </div>
          <p id="passage-note" aria-live="polite" className="text-body-s empty:hidden">
            {state.note?.text}
          </p>
          {preview.failed && (
            <p role="alert" className="text-body-s font-bold text-danger">
              The clip could not be played. Check your connection and try again.
            </p>
          )}
          <p className="text-body-s text-ink-muted">
            Each check plays 3 seconds around the cut, so your first full listen stays fresh for
            Blind. Times are minutes and seconds, for example 02:10; any part from 30 seconds to 15
            minutes.
          </p>
          {mediaUrl && <audio ref={audioRef} src={mediaUrl} preload="none" hidden />}
        </section>
      )}
      <p role="status" className="sr-only">
        {announced}
      </p>
    </div>
  );
}

function wholeNote(durationMs: number): string {
  if (durationMs > MAX_PASSAGE_MS)
    return 'Too long to use whole. Choose a part of 15 minutes or less.';
  if (durationMs < MIN_PASSAGE_MS) return 'Too short: a plan needs at least 30 seconds.';
  if (durationMs > 5 * 60_000) return 'Within the 15-minute limit. Long for Dictation.';
  return 'Within the 15-minute limit.';
}

function TimeField({
  handle,
  durationMs,
  state,
  base,
  dispatch,
}: {
  handle: Handle;
  durationMs: number;
  state: PassageState;
  base: Range;
  dispatch: (action: PassageAction) => void;
}) {
  const id = `passage-${handle}`;
  const error = state.errors[handle];
  const noted = state.note?.handle === handle;
  const describedBy = error ? `${id}-error` : noted ? 'passage-note' : undefined;
  return (
    <div className="flex min-w-0 flex-col gap-1 sm:w-36">
      <label htmlFor={id} className="font-bold">
        {handle === 'start' ? 'Start' : 'End'}
      </label>
      <input
        id={id}
        className="min-h-11 w-full rounded-md border border-line-strong bg-surface-raised px-3 font-mono aria-invalid:border-danger"
        inputMode="numeric"
        autoComplete="off"
        value={textOf(state, base, handle)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event) => dispatch({ type: 'type', handle, text: event.target.value })}
        onBlur={() => dispatch({ type: 'commit', handle, base, durationMs })}
      />
      {error && (
        <p id={`${id}-error`} className="text-body-s font-bold text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** The design system's filled play triangle (16 px grid). */
function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" className="size-4 fill-current">
      <path d="M5 3l9 5-9 5z" />
    </svg>
  );
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

/**
 * Plays a few seconds around a cut (`previewWindow`) and stops by itself. Playing another
 * cut first stops the one playing.
 */
function usePreview(audioRef: RefObject<HTMLAudioElement | null>, durationMs: number) {
  const stopRef = useRef<(() => void) | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => () => stopRef.current?.(), []);

  function hear(cutMs: number) {
    const audio = audioRef.current;
    if (!audio) return;
    stopRef.current?.();
    const { fromMs, toMs } = previewWindow(cutMs, durationMs);
    let timer: number | undefined;
    const stop = () => {
      window.clearTimeout(timer);
      audio.removeEventListener('timeupdate', onTime);
      audio.pause();
      if (stopRef.current === stop) stopRef.current = null;
    };
    const onTime = () => {
      if (audio.currentTime * 1000 >= toMs) stop();
    };
    stopRef.current = stop;
    audio.currentTime = fromMs / 1000;
    audio.addEventListener('timeupdate', onTime);
    audio.play().then(
      () => {
        setFailed(false);
        if (stopRef.current === stop) timer = window.setTimeout(stop, toMs - fromMs);
      },
      () => {
        stop();
        setFailed(true);
      },
    );
  }

  return { hear, failed };
}
