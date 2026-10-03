import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

/** Event types the server streams on GET /api/v1/events (System Design 9.1, ADR 0016). */
export const LIVE_EVENT_TYPES = [
  'job.progress',
  'content.ready',
  'grade.ready',
  'attempt.voided',
] as const;

export type LiveEventType = (typeof LIVE_EVENT_TYPES)[number];

/** One event. It carries ids only: refetch the resource to see what changed. */
export interface LiveEvent {
  id: string;
  type: LiveEventType;
  resourceId: string;
}

/**
 * `open`: events arrive live. `polling`: the stream is down and pending keys refetch every
 * 5 s. `off`: the hook is disabled.
 */
export type LiveStatus = 'connecting' | 'open' | 'polling' | 'off';

export interface LiveEventsOptions {
  /** The query keys to refetch when an event arrives, for example `[['clips', id]]`. */
  keysFor: (event: LiveEvent) => readonly QueryKey[];
  /**
   * Keys of everything the page shows as still pending (a clip being transcribed, a grade
   * being computed). They refetch when the server asks for a resync, after every
   * reconnect, and every 5 s while the stream is down.
   */
  pendingKeys: readonly QueryKey[];
  /** Called with each event after its keys are invalidated, for example to show a notice. */
  onEvent?: (event: LiveEvent) => void;
  /** Turn the stream off, for example while nobody is signed in. */
  enabled?: boolean;
  url?: string;
  pollIntervalMs?: number;
  /** When the browser gives up on the stream (an error response), open a new one after this. */
  reopenAfterMs?: number;
}

export const EVENTS_URL = '/api/v1/events';
export const POLL_INTERVAL_MS = 5000;
export const REOPEN_AFTER_MS = 15000;

function refetch(queryClient: QueryClient, keys: readonly QueryKey[]) {
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
}

function parse(type: LiveEventType, message: MessageEvent<string>): LiveEvent | null {
  try {
    const data = JSON.parse(message.data) as { resource_id?: unknown };
    if (typeof data.resource_id !== 'string') return null;
    return { id: message.lastEventId, type, resourceId: data.resource_id };
  } catch {
    return null;
  }
}

/**
 * Keep queries fresh from the learner's live event stream.
 *
 * Each event invalidates the keys `keysFor` maps it to. The browser reconnects on its own
 * and sends Last-Event-ID, so the server can replay what was missed; when it cannot, it
 * sends `resync`, and the pending keys refetch. While the stream is down the pending keys
 * refetch every 5 s instead.
 */
export function useLiveEvents({
  keysFor,
  pendingKeys,
  onEvent,
  enabled = true,
  url = EVENTS_URL,
  pollIntervalMs = POLL_INTERVAL_MS,
  reopenAfterMs = REOPEN_AFTER_MS,
}: LiveEventsOptions): LiveStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>('connecting');
  // The latest callbacks, without reopening the stream on every render.
  const keysForRef = useRef(keysFor);
  const pendingRef = useRef(pendingKeys);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    keysForRef.current = keysFor;
    pendingRef.current = pendingKeys;
    onEventRef.current = onEvent;
  });

  useEffect(() => {
    if (!enabled) return;
    let source: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | undefined;
    let reopen: ReturnType<typeof setTimeout> | undefined;
    let dropped = false;

    const refetchPending = () => refetch(queryClient, pendingRef.current);

    const startPolling = () => {
      setStatus('polling');
      if (poll === undefined) poll = setInterval(refetchPending, pollIntervalMs);
    };

    const stopPolling = () => {
      clearInterval(poll);
      poll = undefined;
    };

    const open = () => {
      const stream = new EventSource(url);
      source = stream;
      stream.onopen = () => {
        stopPolling();
        setStatus('open');
        // Something may have finished while the stream was down.
        if (dropped) refetchPending();
        dropped = false;
      };
      stream.onerror = () => {
        dropped = true;
        startPolling();
        if (stream.readyState === EventSource.CLOSED) {
          // The browser will not retry this one (an error response): try again later.
          stream.close();
          reopen = setTimeout(open, reopenAfterMs);
        }
      };
      for (const type of LIVE_EVENT_TYPES) {
        stream.addEventListener(type, (message) => {
          const event = parse(type, message);
          if (!event) return;
          refetch(queryClient, keysForRef.current(event));
          onEventRef.current?.(event);
        });
      }
      stream.addEventListener('resync', refetchPending);
    };

    open();
    return () => {
      source?.close();
      stopPolling();
      clearTimeout(reopen);
    };
  }, [enabled, url, pollIntervalMs, reopenAfterMs, queryClient]);

  return enabled ? status : 'off';
}
