import { render, screen, within, waitFor } from '@testing-library/react';
import { renderWithProviders, jsonResponse } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { QueryClientProvider } from '@tanstack/react-query';
import { GistFeedback } from './GistFeedback';

const summary = {
  status: 'ready',
  overall: 80,
  level: 'good',
  dimension_scores: { main_idea: 90, key_details: 70, accuracy: 80 },
  captured_count: 1,
  total_count: 2,
};
const full = {
  ...summary,
  gist: 'My original gist.',
  feedback: 'You caught the idea. Read the detail.',
  key_points: [
    { text: 'The main idea.', captured: true },
    { text: 'The detail.', captured: false },
  ],
};

afterEach(() => vi.restoreAllMocks());

test.each(['blind', 'transcript'] as const)(
  'saved gist remains visible while the %s grade is pending',
  async (context) => {
    mockRoutes({
      'GET /gists/attempt-1/grade': jsonResponse(200, { status: 'pending', gist: full.gist }),
    });
    renderWithProviders(<GistFeedback attemptId="attempt-1" context={context} />);
    expect(await screen.findByText(full.gist)).toBeInTheDocument();
    expect(screen.getByText('Preparing your gist feedback…')).toBeInTheDocument();
    expect(screen.queryByText(/\/ 100/)).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Key points' })).not.toBeInTheDocument();
  },
);

test('D4 summary shows score parts and count without detail', async () => {
  mockRoutes({ 'GET /gists/attempt-1/grade': jsonResponse(200, summary) });
  renderWithProviders(<GistFeedback attemptId="attempt-1" context="blind" />);
  expect(await screen.findByText('80 / 100')).toBeInTheDocument();
  expect(screen.getByText('Good')).toBeInTheDocument();
  expect(screen.getByText('Main idea: 90 / 100')).toBeInTheDocument();
  expect(screen.getByText('You captured 1 of 2 key points')).toBeInTheDocument();
  expect(screen.queryByRole('list', { name: 'Key points' })).not.toBeInTheDocument();
});

test.each(['blind', 'transcript'] as const)(
  'full grade and gist in %s use words for captured and missed',
  async (context) => {
    mockRoutes({ 'GET /gists/attempt-1/grade': jsonResponse(200, full) });
    renderWithProviders(<GistFeedback attemptId="attempt-1" context={context} />);
    expect(await screen.findByText('My original gist.')).toBeInTheDocument();
    expect(screen.getByText(full.feedback)).toBeInTheDocument();
    const points = screen.getByRole('list', { name: 'Key points' });
    expect(within(points).getByText(/Captured.*The main idea/)).toBeInTheDocument();
    expect(within(points).getByText(/Missed.*The detail/)).toBeInTheDocument();
  },
);

test('pending is neutral and does not offer failure or retry actions', async () => {
  mockRoutes({ 'GET /gists/attempt-1/grade': jsonResponse(200, { status: 'pending' }) });
  renderWithProviders(<GistFeedback attemptId="attempt-1" context="blind" />);
  expect(await screen.findByText('Preparing your gist feedback…')).toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('grade.ready fills the pending result in place without moving focus', async () => {
  const { QueryClient } = await import('@tanstack/react-query');
  const { queryKeysForEvent } = await import('../../app/eventKeys');
  let ready = false;
  mockRoutes({
    'GET /gists/attempt-1/grade': () => jsonResponse(200, ready ? full : { status: 'pending' }),
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <button>Keep focus</button>
      <GistFeedback attemptId="attempt-1" context="blind" />
    </QueryClientProvider>,
  );
  const button = screen.getByRole('button', { name: 'Keep focus' });
  button.focus();
  await screen.findByText('Preparing your gist feedback…');
  ready = true;
  const { act } = await import('@testing-library/react');
  await act(async () => {
    for (const key of queryKeysForEvent(
      { id: 'event-69', type: 'grade.ready', resourceId: 'attempt-1' },
      queryClient,
    ))
      await queryClient.invalidateQueries({ queryKey: key });
  });
  expect(await screen.findByText(full.feedback)).toBeInTheDocument();
  expect(button).toHaveFocus();
});

test('unavailable feedback keeps the gist and offers one guarded retry', async () => {
  const { fireEvent } = await import('@testing-library/react');
  let finish!: (response: Response) => void;
  const { calls } = mockRoutes({
    'GET /gists/attempt-1/grade': jsonResponse(200, { status: 'unavailable', gist: full.gist }),
    'POST /grades/attempt-1/retry': () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  });
  renderWithProviders(<GistFeedback attemptId="attempt-1" context="blind" />);
  expect(await screen.findByText('Feedback unavailable')).toBeInTheDocument();
  expect(screen.getByText(full.gist)).toBeInTheDocument();
  const retry = screen.getByRole('button', { name: 'Retry feedback' });
  retry.focus();
  fireEvent.click(retry);
  fireEvent.click(retry);
  await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1));
  expect(retry).toHaveFocus();
  expect(retry).toHaveAttribute('aria-disabled', 'true');
  const { act } = await import('@testing-library/react');
  await act(async () => finish(jsonResponse(202, { status: 'accepted' })));
});

test('quota waiting says delayed and a late result preserves focus', async () => {
  const { QueryClient } = await import('@tanstack/react-query');
  let ready = false;
  mockRoutes({
    'GET /gists/attempt-1/grade': () =>
      jsonResponse(200, ready ? full : { status: 'delayed', gist: full.gist }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <button>Continue</button>
      <GistFeedback attemptId="attempt-1" context="transcript" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText('Feedback delayed')).toBeInTheDocument();
  const next = screen.getByRole('button', { name: 'Continue' });
  next.focus();
  ready = true;
  const { act } = await import('@testing-library/react');
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['sessions', 'gist-grade'] });
  });
  expect(await screen.findByText(full.feedback)).toBeInTheDocument();
  expect(next).toHaveFocus();
});

test('the server deadline ends the spinner even when the next read stalls', async () => {
  const { act } = await import('@testing-library/react');
  vi.useFakeTimers();
  let first = true;
  mockRoutes({
    'GET /gists/attempt-1/grade': () => {
      if (!first) return new Promise<Response>(() => {});
      first = false;
      return jsonResponse(200, { status: 'pending', wait_ms: 30_000, gist: full.gist });
    },
  });
  try {
    await act(async () => {
      renderWithProviders(<GistFeedback attemptId="attempt-1" context="blind" />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByText(full.gist)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.getByText('Feedback unavailable')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Gist feedback' })).toHaveAttribute(
      'aria-busy',
      'false',
    );
  } finally {
    vi.useRealTimers();
  }
});
