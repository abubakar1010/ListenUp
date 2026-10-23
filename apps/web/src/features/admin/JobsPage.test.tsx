import { fireEvent, screen, within } from '@testing-library/react';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import type { FailedJob, JobsOverview } from './adminApi';
import { formatWait } from './formatWait';
import JobsPage from './JobsPage';

afterEach(() => vi.restoreAllMocks());

const LANES: JobsOverview['lanes'] = [
  { lane: 'speech-interactive', waiting: 0, scheduled: 0, running: 1, oldest_wait_seconds: null },
  { lane: 'intake', waiting: 3, scheduled: 1, running: 2, oldest_wait_seconds: 95 },
  { lane: 'ai', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
  { lane: 'background', waiting: 0, scheduled: 0, running: 0, oldest_wait_seconds: null },
];

const FAILED: FailedJob = {
  id: 12,
  lane: 'intake',
  name: 'content.convert_upload',
  attempts: 5,
  failed_at: '2026-10-08T09:30:00Z',
};

test('an admin sees the backlog of every lane and the failed jobs', async () => {
  mockRoutes({ 'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed: [FAILED] }) });
  renderWithProviders(<JobsPage />);

  const backlog = await screen.findByRole('table', { name: /jobs per lane/i });
  const intake = within(backlog).getByRole('row', { name: /^Intake/ });
  expect(
    within(intake)
      .getAllByRole('cell')
      .map((cell) => cell.textContent),
  ).toEqual(['3', '1', '2', '1 min']);
  expect(within(backlog).getAllByRole('row')).toHaveLength(5);

  const failed = screen.getByRole('table', { name: /failed jobs/i });
  expect(within(failed).getByRole('rowheader')).toHaveTextContent('content.convert_upload #12');
  expect(within(failed).getByRole('button', { name: 'Retry job 12, content.convert_upload' }));
  expect(document.title).toBe('Jobs · ListenUp');
});

test('each table scrolls in its own named region that the keyboard can reach', async () => {
  mockRoutes({ 'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed: [FAILED] }) });
  renderWithProviders(<JobsPage />);

  const backlog = await screen.findByRole('region', { name: 'Backlog table' });
  const failed = screen.getByRole('region', { name: 'Failed jobs table' });
  for (const region of [backlog, failed]) expect(region).toHaveAttribute('tabindex', '0');
  expect(within(backlog).getByRole('table')).toBeInTheDocument();
  expect(within(failed).getByRole('table')).toBeInTheDocument();
});

test('retrying a job queues it again, says so and reloads the list', async () => {
  let failed = [FAILED];
  const { calls } = mockRoutes({
    'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed }),
    'POST /admin/jobs/12/retry': () => {
      failed = [];
      return jsonResponse(202, { job_id: 40 });
    },
  });
  renderWithProviders(<JobsPage />);

  fireEvent.click(await screen.findByRole('button', { name: /Retry job 12/ }));

  expect(await screen.findByText('Job 12 was queued again as job 40.')).toBeInTheDocument();
  expect(await screen.findByText('No failed jobs.')).toBeInTheDocument();
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
});

test('a retry whose work is already queued explains why', async () => {
  mockRoutes({
    'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed: [FAILED] }),
    'POST /admin/jobs/12/retry': () => problem(409, 'job_already_queued', 'Already waiting.'),
  });
  renderWithProviders(<JobsPage />);

  fireEvent.click(await screen.findByRole('button', { name: /Retry job 12/ }));

  expect(await screen.findByText(/the same work is already waiting/)).toBeInTheDocument();
});

test('someone who is not an admin sees the ordinary page-not-found', async () => {
  mockRoutes({ 'GET /admin/jobs': () => problem(404, 'not_found', 'Not Found') });
  renderWithProviders(<JobsPage />);

  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

test('waits read in seconds, minutes or hours', () => {
  expect(formatWait(null)).toBe('—');
  expect(formatWait(12.4)).toBe('12 s');
  expect(formatWait(95)).toBe('1 min');
  expect(formatWait(3 * 3600 + 120)).toBe('3 h 2 min');
});

test('a job that is no longer failed says so and the list is reloaded', async () => {
  let failed = [FAILED];
  mockRoutes({
    'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed }),
    'POST /admin/jobs/12/retry': () => {
      failed = [];
      return problem(404, 'job_not_found', 'Not failed.');
    },
  });
  renderWithProviders(<JobsPage />);

  fireEvent.click(await screen.findByRole('button', { name: /Retry job 12/ }));

  expect(await screen.findByText(/no longer waiting for a retry/)).toBeInTheDocument();
  expect(await screen.findByText('No failed jobs.')).toBeInTheDocument();
});

test('any other refusal of a retry is shown with what to do next', async () => {
  mockRoutes({
    'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed: [FAILED] }),
    'POST /admin/jobs/12/retry': () => problem(500, 'internal_error', 'Boom.'),
  });
  renderWithProviders(<JobsPage />);

  fireEvent.click(await screen.findByRole('button', { name: /Retry job 12/ }));

  expect(await screen.findByText(/^Job 12 was not retried\./)).toBeInTheDocument();
  expect(screen.getByRole('table', { name: /failed jobs/i })).toBeInTheDocument();
});

test('Refresh loads the jobs again', async () => {
  const { calls } = mockRoutes({
    'GET /admin/jobs': () => jsonResponse(200, { lanes: LANES, failed: [] }),
  });
  renderWithProviders(<JobsPage />);
  await screen.findByRole('table', { name: /jobs per lane/i });

  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

  await vi.waitFor(() => expect(calls.filter((c) => c.method === 'GET')).toHaveLength(2));
});

test('a list that cannot load offers to try again', async () => {
  let attempts = 0;
  mockRoutes({
    'GET /admin/jobs': () => {
      attempts += 1;
      // The page retries a failing load twice before it shows the error.
      return attempts <= 3
        ? problem(503, 'service_unavailable', 'The service is busy.')
        : jsonResponse(200, { lanes: LANES, failed: [] });
    },
  });
  renderWithProviders(<JobsPage />);

  const alert = await screen.findByRole('alert', {}, { timeout: 8000 });
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));

  expect(await screen.findByRole('table', { name: /jobs per lane/i })).toBeInTheDocument();
}, 15_000);
