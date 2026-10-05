import { act, fireEvent, screen, within } from '@testing-library/react';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { DataExportSection } from './DataExportSection';
import { EXPORT_POLL_MS, type DataExport } from './exportApi';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function exportFixture(overrides: Partial<DataExport> = {}): DataExport {
  return {
    id: 'e1',
    status: 'pending',
    requested_at: '2026-10-04T09:00:00Z',
    ready_at: null,
    expires_at: null,
    archive_bytes: null,
    file_count: null,
    download_url: null,
    ...overrides,
  };
}

const READY = exportFixture({
  status: 'ready',
  ready_at: '2026-10-04T09:02:00Z',
  expires_at: '2026-10-11T09:02:00Z',
  archive_bytes: 25 * 1024 * 1024,
  file_count: 3,
  download_url: '/api/v1/me/exports/e1/download',
});

async function section() {
  return screen.findByRole('region', { name: 'Download your data' });
}

test('asking for a copy shows that it is being prepared, then offers the download', async () => {
  let current: DataExport | null = null;
  const { calls } = mockRoutes({
    'GET /me/exports/latest': () => jsonResponse(200, { export: current }),
    'POST /me/exports': () => {
      current = exportFixture();
      return jsonResponse(202, current);
    },
  });
  renderWithProviders(<DataExportSection />);

  const region = await section();
  expect(
    await within(region).findByText('You have not asked for a copy of your data yet.'),
  ).toBeInTheDocument();
  expect(region).toHaveTextContent('Files of clips you added from YouTube are not included');

  fireEvent.click(within(region).getByRole('button', { name: 'Prepare my download' }));
  expect(await within(region).findByRole('button', { name: 'Preparing…' })).toBeDisabled();
  expect(within(region).getByRole('status')).toHaveTextContent('We are preparing your download.');
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
  expect(within(region).queryByRole('link')).not.toBeInTheDocument();
});

test('a ready export links to the download endpoint and says how long it is kept', async () => {
  mockRoutes({ 'GET /me/exports/latest': jsonResponse(200, { export: READY }) });
  renderWithProviders(<DataExportSection />);

  const region = await section();
  const link = await within(region).findByRole('link', { name: 'Download your data (ZIP)' });
  expect(link).toHaveAttribute('href', '/api/v1/me/exports/e1/download');
  expect(within(region).getByRole('status')).toHaveTextContent(
    /ready \(25 MB, 3 media files and your data as JSON\)\. It is kept until 11 October/,
  );
  expect(within(region).getByRole('button', { name: 'Prepare a new download' })).toBeEnabled();
});

test('while it is prepared, the status is checked again until it is ready', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let current = exportFixture({ status: 'building' });
  mockRoutes({ 'GET /me/exports/latest': () => jsonResponse(200, { export: current }) });
  renderWithProviders(<DataExportSection />);

  const region = await section();
  await within(region).findByRole('button', { name: 'Preparing…' });
  current = READY;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(EXPORT_POLL_MS);
  });
  expect(
    await within(region).findByRole('link', { name: 'Download your data (ZIP)' }),
  ).toBeInTheDocument();
});

test('failed and expired exports say what happened and can be asked for again', async () => {
  let current = exportFixture({ status: 'failed' });
  mockRoutes({ 'GET /me/exports/latest': () => jsonResponse(200, { export: current }) });
  const { unmount } = renderWithProviders(<DataExportSection />);
  const region = await section();
  expect(await within(region).findByText(/We could not prepare your download\./)).toHaveAttribute(
    'role',
    'status',
  );
  expect(within(region).getByRole('button', { name: 'Prepare a new download' })).toBeEnabled();
  unmount();

  current = exportFixture({ status: 'expired', expires_at: '2026-10-01T00:00:00Z' });
  renderWithProviders(<DataExportSection />);
  expect(
    await within(await section()).findByText(/Your last download has expired/),
  ).toBeInTheDocument();
});

test('the daily limit is explained with when the learner can ask again', async () => {
  mockRoutes({
    'GET /me/exports/latest': jsonResponse(200, { export: null }),
    'POST /me/exports': () => {
      const response = problem(429, 'rate_limited', 'Too many requests. Try again later.');
      response.headers.set('Retry-After', '3600');
      return response;
    },
  });
  renderWithProviders(<DataExportSection />);

  const region = await section();
  fireEvent.click(await within(region).findByRole('button', { name: 'Prepare my download' }));
  const alert = await within(region).findByRole('alert');
  expect(alert).toHaveTextContent('You have asked for several downloads today');
  expect(alert).toHaveTextContent(/You can ask for a new one at \d\d:\d\d/);
});

test('a status that cannot be loaded shows the error with a retry', async () => {
  mockRoutes({
    'GET /me/exports/latest': problem(503, 'database_unavailable', 'The service is busy.'),
  });
  renderWithProviders(<DataExportSection />);

  const region = await section();
  expect(await within(region).findByRole('alert')).toHaveTextContent('The service is busy.');
  expect(within(region).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});
