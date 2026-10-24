import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';

import { queryKeysForEvent } from '../../app/eventKeys';
import { useLiveEvents, type LiveEvent } from '../../events/useLiveEvents';
import { jsonResponse, problem } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { DICTATION_RESULT_KEY, useDictationResult } from './api';
import { DictationResultPanel } from './DictationResultPanel';
import { RESULT } from './fixtures';

const WAITING = /Scoring when the transcript is ready/;
const PATH = '/sessions/session-1/dictation/attempt';
const view = (scoring_status: string | null, result: unknown = null) => ({
  id: 'attempt-1',
  session_id: 'session-1',
  status: 'submitted',
  scoring_status,
  result,
});

type Listener = (event: MessageEvent<string>) => void;
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static latest: FakeEventSource | null = null;
  readyState = FakeEventSource.OPEN;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();
  constructor() {
    FakeEventSource.latest = this;
  }
  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(type: string, resourceId: string) {
    const message = new MessageEvent<string>(type, {
      data: JSON.stringify({ type, resource_id: resourceId }),
    });
    for (const listener of this.listeners.get(type) ?? []) listener(message);
  }
}

/** The panel with the same live-event wiring as the signed-in app (guards.tsx). */
function Harness({ children, client }: { children: ReactNode; client: QueryClient }) {
  useLiveEvents({
    keysFor: (event: LiveEvent) => queryKeysForEvent(event, client),
    pendingKeys: [],
  });
  return children;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Harness client={client}>
          <DictationResultPanel sessionId="session-1" />
        </Harness>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('a submission waiting for the transcript says it will be scored when it is ready', async () => {
  mockRoutes({ [`GET ${PATH}`]: jsonResponse(200, view('waiting_transcript')) });

  renderPanel();

  const status = await screen.findByRole('status');
  expect(status).toHaveTextContent('Scoring when the transcript is ready');
  expect(screen.queryByRole('list', { name: 'Word by word' })).not.toBeInTheDocument();
});

test('a failed transcript says scoring is unavailable, and a later score replaces it', async () => {
  let scored = false;
  mockRoutes({
    [`GET ${PATH}`]: () =>
      jsonResponse(200, scored ? view('scored', RESULT) : view('scoring_unavailable')),
  });
  renderPanel();

  const status = await screen.findByRole('status');
  expect(status).toHaveTextContent('We could not score this Dictation');
  expect(screen.queryByText(WAITING)).not.toBeInTheDocument();

  scored = true;
  await act(async () => FakeEventSource.latest!.emit('dictation.scored', 'attempt-1'));
  expect(await screen.findByText('90%')).toBeInTheDocument();
});

test('the result replaces the waiting message when dictation.scored arrives, without a reload', async () => {
  let scored = false;
  const { calls } = mockRoutes({
    [`GET ${PATH}`]: () =>
      jsonResponse(200, scored ? view('scored', RESULT) : view('waiting_transcript')),
  });
  renderPanel();
  await screen.findByText(WAITING);

  scored = true;
  await act(async () => FakeEventSource.latest!.emit('dictation.scored', 'attempt-1'));

  expect(await screen.findByText('90%')).toBeInTheDocument();
  expect(screen.queryByText(WAITING)).not.toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Word by word' })).toBeInTheDocument();
  expect(calls.filter((call) => call.path === PATH)).toHaveLength(2);
});

test('shows nothing when the session has no Dictation attempt', async () => {
  mockRoutes({ [`GET ${PATH}`]: problem(404, 'attempt_not_found', 'No attempt.') });

  renderPanel();

  await act(async () => undefined);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('a failed read shows the problem with a retry', async () => {
  mockRoutes({ [`GET ${PATH}`]: problem(500, 'internal_error', 'Something broke.') });

  renderPanel();

  expect(await screen.findByRole('alert')).toHaveTextContent('Something broke.');
  expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
});

test('a result nobody is looking at is dropped, so a live event never refetches it', async () => {
  mockRoutes({ [`GET ${PATH}`]: jsonResponse(200, view('scored', RESULT)) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(() => useDictationResult('session-1'), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  vi.useFakeTimers();
  unmount();
  await vi.advanceTimersByTimeAsync(60_000);
  vi.useRealTimers();

  expect(client.getQueryCache().findAll({ queryKey: DICTATION_RESULT_KEY })).toHaveLength(0);
});

test('a scored result offers its missed and wrong words for the mark list (FR-DI-6)', async () => {
  mockRoutes({
    [`GET ${PATH}`]: jsonResponse(200, view('scored', RESULT)),
    'GET /dictation/attempts/attempt-1/marks': jsonResponse(200, { marks: [] }),
  });

  renderPanel();

  expect(await screen.findByRole('heading', { name: 'Add to your marks' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add “to cool” to marks' })).toBeInTheDocument();
});
