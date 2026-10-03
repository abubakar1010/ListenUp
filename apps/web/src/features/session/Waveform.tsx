import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from 'react';

import {
  bucketPeaks,
  dragStepMs,
  handleBounds,
  keyTarget,
  moveHandle,
  nearerHandle,
  snapMs,
  spokenTime,
  type Handle,
  type Peaks,
  type Range,
} from './passage';

interface WaveformProps {
  durationMs: number;
  range: Range;
  /** Null while the peaks load, or when they could not be loaded: the track is drawn bare. */
  peaks: Peaks | null;
  onChange: (range: Range) => void;
}

/** Bars drawn when the track's width is not known yet (and in tests). */
const FALLBACK_BARS = 120;
/** One bar every 3 px: 2 px of bar and 1 px of gap. */
const PX_PER_BAR = 3;

/**
 * The clip's waveform with the passage's start and end handles (ADR 0026). Each handle is
 * a slider: drag it, or focus it and use the arrow keys (1 s), Shift + arrows or Page
 * Up/Down (5 s), Home and End. Pressing on the track moves the nearer handle there.
 */
export function Waveform({ durationMs, range, peaks, onChange }: WaveformProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const startRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const dragging = useRef<Handle | null>(null);
  const [width, setWidth] = useState(0);
  const clipId = useId();

  useEffect(() => {
    const track = trackRef.current;
    if (!track || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(track);
    return () => observer.disconnect();
  }, []);

  const bars = useMemo(
    () =>
      peaks ? bucketPeaks(peaks, width > 0 ? Math.floor(width / PX_PER_BAR) : FALLBACK_BARS) : [],
    [peaks, width],
  );
  const barsPath = useMemo(() => {
    let d = '';
    for (let i = 0; i < bars.length; i += 1) {
      const height = Math.max(4, bars[i] * 100);
      d += `M${i + 0.15} ${(100 - height) / 2}h0.7v${height}h-0.7z`;
    }
    return d;
  }, [bars]);

  const percent = (ms: number) => (ms / durationMs) * 100;
  const startPct = percent(range.startMs);
  const endPct = percent(range.endMs);

  function msAt(clientX: number): number {
    const rect = trackRef.current!.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return ratio * durationMs;
  }

  function dragTo(handle: Handle, ms: number) {
    const widthPx = width || trackRef.current?.getBoundingClientRect().width || 0;
    const snapped = snapMs(ms, dragStepMs(durationMs, widthPx), durationMs);
    onChange(moveHandle(range, handle, snapped, durationMs));
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const ms = msAt(event.clientX);
    const hit = (event.target as HTMLElement).dataset.handle as Handle | undefined;
    const handle = hit ?? nearerHandle(range, ms);
    dragging.current = handle;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    (handle === 'start' ? startRef : endRef).current?.focus();
    if (!hit) dragTo(handle, ms);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (dragging.current) dragTo(dragging.current, msAt(event.clientX));
  }

  function onPointerEnd() {
    dragging.current = null;
  }

  function slider(handle: Handle) {
    const value = handle === 'start' ? range.startMs : range.endMs;
    const bounds = handleBounds(range, handle, durationMs);
    return (
      <div
        ref={handle === 'start' ? startRef : endRef}
        data-handle={handle}
        role="slider"
        tabIndex={0}
        aria-label={handle === 'start' ? 'Passage start' : 'Passage end'}
        aria-valuemin={Math.floor(bounds.min / 1000)}
        aria-valuemax={Math.floor(bounds.max / 1000)}
        aria-valuenow={Math.floor(value / 1000)}
        aria-valuetext={spokenTime(value)}
        onKeyDown={(event) => {
          const target = keyTarget(value, event.key, event.shiftKey, bounds);
          if (target === null) return;
          event.preventDefault();
          onChange(moveHandle(range, handle, target, durationMs));
        }}
        style={{ left: `${percent(value)}%` }}
        className="absolute top-1/2 z-10 h-11 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-sm border-2 border-surface-raised bg-accent before:absolute before:inset-y-0 before:-right-3 before:-left-3 before:content-['']"
      />
    );
  }

  return (
    <div className="h-18 rounded-sm bg-surface-sunken px-2 md:h-24">
      <div
        ref={trackRef}
        className="relative h-full touch-pan-y select-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
      >
        <div
          aria-hidden="true"
          className="absolute inset-y-0 border-x-[3px] border-accent bg-accent-soft"
          style={{ left: `${startPct}%`, width: `${endPct - startPct}%` }}
        />
        {bars.length > 0 && (
          <svg
            aria-hidden="true"
            data-testid="waveform-bars"
            className="absolute inset-x-0 inset-y-3 h-[calc(100%-1.5rem)] w-full md:inset-y-4 md:h-[calc(100%-2rem)]"
            viewBox={`0 0 ${bars.length} 100`}
            preserveAspectRatio="none"
          >
            <defs>
              <clipPath id={clipId}>
                <rect
                  x={(startPct / 100) * bars.length}
                  width={((endPct - startPct) / 100) * bars.length}
                  y="0"
                  height="100"
                />
              </clipPath>
            </defs>
            <path d={barsPath} className="fill-line-strong" />
            <path d={barsPath} className="fill-accent" clipPath={`url(#${clipId})`} />
          </svg>
        )}
        {slider('start')}
        {slider('end')}
      </div>
    </div>
  );
}
