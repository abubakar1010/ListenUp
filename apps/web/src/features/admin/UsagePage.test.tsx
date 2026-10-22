import { fireEvent, screen, within } from '@testing-library/react';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import UsagePage from './UsagePage';

afterEach(() => vi.restoreAllMocks());

const REPORT = {
  start_date: '2026-10-01',
  end_date: '2026-10-30',
  as_of: '2026-10-30T23:30:00Z',
  providers: [
    {
      provider: 'hosted',
      days: [
        {
          date: '2026-10-30',
          calls: 2,
          input_tokens: 300,
          output_tokens: 50,
          audio_seconds: 4,
          estimated_cost_usd: 0.25,
          estimated_calls: 1,
        },
      ],
      quotas: [
        {
          period: 'day',
          calls: 2,
          tokens: 350,
          audio_seconds: 4,
          limits: { calls: 10, tokens: 1000 },
        },
        { period: 'month', calls: 3, tokens: 375, audio_seconds: 4, limits: null },
      ],
    },
  ],
};

test('an admin sees daily units, hypothetical cost and free quota with distinct periods', async () => {
  mockRoutes({ 'GET /admin/usage': () => jsonResponse(200, REPORT) });
  renderWithProviders(<UsagePage />);
  const daily = await screen.findByRole('table', { name: 'hosted daily usage (UTC)' });
  expect(within(daily).getByRole('row', { name: /2026-10-30/ })).toHaveTextContent('300');
  expect(within(daily).getByText('$0.2500')).toBeInTheDocument();
  expect(screen.getByText('2 / 10 (20%)')).toBeInTheDocument();
  expect(screen.getByText('350 / 1,000 (35%)')).toBeInTheDocument();
  expect(screen.getByText('Unknown allowance; 3 used')).toBeInTheDocument();
  expect(screen.getByText(/not billed spend/i)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Jobs' })).toHaveAttribute('href', '/admin/jobs');
  expect(document.title).toBe('AI usage · ListenUp');
});

test('zero allowance and uncapped dimensions do not appear as unused free quota', async () => {
  const report = structuredClone(REPORT);
  report.providers[0].quotas[0].limits = { calls: 0, tokens: 1000 };
  mockRoutes({ 'GET /admin/usage': () => jsonResponse(200, report) });
  renderWithProviders(<UsagePage />);
  expect(await screen.findByText('No allowance (0); 2 used')).toBeInTheDocument();
  expect(screen.getByText('Uncapped; 4 used')).toBeInTheDocument();
});

test('a learner sees the ordinary 404 without usage or admin navigation', async () => {
  mockRoutes({ 'GET /admin/usage': () => problem(404, 'not_found', 'Not Found') });
  renderWithProviders(<UsagePage />);
  expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Jobs' })).not.toBeInTheDocument();
});

test('a failed report can be retried and an empty report says there is no usage', async () => {
  let attempts = 0;
  mockRoutes({
    'GET /admin/usage': () =>
      ++attempts === 1
        ? problem(503, 'usage_unavailable', 'Usage reporting is unavailable.')
        : jsonResponse(200, { ...REPORT, providers: [] }),
  });
  renderWithProviders(<UsagePage />);
  fireEvent.click(await screen.findByRole('button', { name: /try again/i }));
  expect(await screen.findByText('No provider usage or configured quotas.')).toBeInTheDocument();
});

test('loading is announced before any usage is displayed', () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => {}));
  renderWithProviders(<UsagePage />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading usage…');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

test('Refresh replaces the displayed usage with a fresh report', async () => {
  let refreshed = false;
  mockRoutes({
    'GET /admin/usage': () => {
      const report = structuredClone(REPORT);
      if (refreshed) report.providers[0].days[0].calls = 4;
      return jsonResponse(200, report);
    },
  });
  renderWithProviders(<UsagePage />);
  const daily = await screen.findByRole('table', { name: 'hosted daily usage (UTC)' });
  const calls = () => within(daily).getAllByRole('cell')[0];
  expect(calls()).toHaveTextContent('2');
  refreshed = true;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByRole('button', { name: 'Refresh' });
  expect(calls()).toHaveTextContent('4');
});
