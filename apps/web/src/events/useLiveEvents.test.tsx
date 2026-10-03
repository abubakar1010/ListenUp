import { QueryClient, QueryClientProvider, type QueryKey } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';

import { useLiveEvents, type LiveEvent, type LiveEventsOptions } from './useLiveEvents';

type Listener = (event: MessageEvent<string>) => void;

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  static get latest(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  /** The connection dropped; the browser keeps retrying unless `closed`. */
  fail({ closed = false } = {}) {
    this.readyState = closed ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
    this.onerror?.();
  }

  emit(type: string, data: unknown, id = '') {
    const event = new MessageEvent<string>(type, {
      data: JSON.stringify(data),
      lastEventId: id,
    });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

const PENDING: QueryKey[] = [['clips', 'pending']];

function setup(options: Partial<LiveEventsOptions> = {}) {
  const queryClient = new QueryClient();
  const invalidated: QueryKey[] = [];
  vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(async (filters) => {
    if (filters?.queryKey) invalidated.push(filters.queryKey);
  });
  const keysFor = vi.fn((event: LiveEvent): QueryKey[] => [['resource', event.resourceId]]);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    (props: Partial<LiveEventsOptions>) =>
      useLiveEvents({ keysFor, pendingKeys: PENDING, ...options, ...props }),
    { wrapper, initialProps: {} },
  );
  return { ...hook, invalidated, keysFor };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useLiveEvents', () => {
  it('opens the learner event stream', () => {
    const { result } = setup();

    expect(FakeEventSource.latest.url).toBe('/api/v1/events');
    expect(result.current).toBe('connecting');
    act(() => FakeEventSource.latest.open());
    expect(result.current).toBe('open');
  });

  it('refetches the resource an event names', () => {
    const { invalidated, keysFor } = setup();
    act(() => FakeEventSource.latest.open());

    act(() =>
      FakeEventSource.latest.emit(
        'content.ready',
        { type: 'content.ready', resource_id: 'clip-1' },
        'abcd-3',
      ),
    );

    expect(keysFor).toHaveBeenCalledWith({
      id: 'abcd-3',
      type: 'content.ready',
      resourceId: 'clip-1',
    });
    expect(invalidated).toEqual([['resource', 'clip-1']]);
  });

  it('hands each event to onEvent after refetching, and skips malformed ones', () => {
    const onEvent = vi.fn();
    const { invalidated } = setup({ onEvent });
    act(() => FakeEventSource.latest.open());

    act(() => {
      FakeEventSource.latest.emit(
        'content.ready',
        { type: 'content.ready', resource_id: 'clip-1' },
        'abcd-4',
      );
      FakeEventSource.latest.emit('content.ready', { type: 'content.ready' });
    });

    expect(invalidated).toEqual([['resource', 'clip-1']]);
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({
      id: 'abcd-4',
      type: 'content.ready',
      resourceId: 'clip-1',
    });
  });

  it('handles every event type and ignores malformed data', () => {
    const { invalidated } = setup();
    act(() => FakeEventSource.latest.open());

    act(() => {
      for (const type of ['job.progress', 'grade.ready', 'attempt.voided']) {
        FakeEventSource.latest.emit(type, { type, resource_id: type });
      }
      FakeEventSource.latest.emit('grade.ready', { type: 'grade.ready' });
    });

    expect(invalidated).toEqual([
      ['resource', 'job.progress'],
      ['resource', 'grade.ready'],
      ['resource', 'attempt.voided'],
    ]);
  });

  it('refetches everything pending when the server asks for a resync', () => {
    const { invalidated } = setup();
    act(() => FakeEventSource.latest.open());

    act(() => FakeEventSource.latest.emit('resync', { type: 'resync' }));

    expect(invalidated).toEqual(PENDING);
  });

  it('polls every 5 s while the stream is down, then stops and refetches on reconnect', () => {
    const { result, invalidated } = setup();
    act(() => FakeEventSource.latest.open());

    act(() => FakeEventSource.latest.fail());
    expect(result.current).toBe('polling');
    act(() => vi.advanceTimersByTime(4999));
    expect(invalidated).toEqual([]);
    act(() => vi.advanceTimersByTime(1));
    expect(invalidated).toEqual(PENDING);
    act(() => vi.advanceTimersByTime(5000));
    expect(invalidated).toEqual([...PENDING, ...PENDING]);

    // The browser reconnects the same EventSource on its own.
    act(() => FakeEventSource.latest.open());
    expect(result.current).toBe('open');
    expect(invalidated).toEqual([...PENDING, ...PENDING, ...PENDING]);
    act(() => vi.advanceTimersByTime(20000));
    expect(invalidated).toHaveLength(3);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it('polls while it cannot connect at all', () => {
    const { result, invalidated } = setup();

    act(() => FakeEventSource.latest.fail());
    act(() => vi.advanceTimersByTime(10000));

    expect(result.current).toBe('polling');
    expect(invalidated).toEqual([...PENDING, ...PENDING]);
  });

  it('opens a new stream later when the browser gives up on one', () => {
    const { invalidated } = setup();
    act(() => FakeEventSource.latest.open());

    act(() => FakeEventSource.latest.fail({ closed: true }));
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(15000));

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(invalidated).toEqual([...PENDING, ...PENDING, ...PENDING]);
    act(() => FakeEventSource.latest.open());
    expect(invalidated).toHaveLength(4);
  });

  it('closes the stream and stops polling when unmounted or disabled', () => {
    const { rerender, unmount, result, invalidated } = setup();
    const first = FakeEventSource.latest;
    act(() => first.fail());

    rerender({ enabled: false });
    expect(first.readyState).toBe(FakeEventSource.CLOSED);
    expect(result.current).toBe('off');
    act(() => vi.advanceTimersByTime(20000));
    expect(invalidated).toEqual([]);

    rerender({ enabled: true });
    expect(FakeEventSource.instances).toHaveLength(2);
    unmount();
    expect(FakeEventSource.latest.readyState).toBe(FakeEventSource.CLOSED);
  });

  it('uses the latest key mapping without reopening the stream', () => {
    const { rerender, invalidated } = setup();
    act(() => FakeEventSource.latest.open());

    rerender({ keysFor: (event: LiveEvent) => [['other', event.resourceId]] });
    act(() =>
      FakeEventSource.latest.emit('grade.ready', { type: 'grade.ready', resource_id: 'g-1' }),
    );

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(invalidated).toEqual([['other', 'g-1']]);
  });
});
