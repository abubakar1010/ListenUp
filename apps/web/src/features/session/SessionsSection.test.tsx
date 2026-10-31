import { fireEvent, screen, within } from '@testing-library/react';

import { jsonResponse, renderWithProviders } from '../../test-utils';
import { sessionFixture } from './fixtures';
import { SessionsSection } from './SessionsSection';
import { mockRoutes } from './testApi';

afterEach(() => vi.restoreAllMocks());

test('plans list where each one stands, newest activity first, with more on demand', async () => {
  mockRoutes({
    'GET /sessions': jsonResponse(200, {
      items: [
        sessionFixture({ id: 's2', entry: 'both', done: 1 }),
        sessionFixture({ id: 's1', done: 4, content_title: 'Podcast ep. 41' }),
      ],
      next_cursor: 'next/1',
    }),
    'GET /sessions?cursor=next%2F1': jsonResponse(200, {
      items: [sessionFixture({ id: 's0', entry: 'dictation', content_title: 'Interview' })],
      next_cursor: null,
    }),
  });
  renderWithProviders(<SessionsSection />);

  const section = await screen.findByRole('region', { name: 'Your plans' });
  const rows = within(section).getAllByRole('listitem');
  expect(rows[0]).toHaveTextContent('02:10 to 04:40 · Step 2 of 5 · Dictation');
  expect(
    within(rows[0]).getByRole('link', { name: 'Resume Why cities plant street trees' }),
  ).toHaveAttribute('href', '/sessions/s2');
  expect(rows[1]).toHaveTextContent('All 4 steps finished');
  expect(within(rows[1]).getByRole('link', { name: 'View Podcast ep. 41' })).toBeInTheDocument();

  fireEvent.click(within(section).getByRole('button', { name: 'More plans' }));
  expect(await within(section).findByText('Interview', { selector: 'b' })).toBeInTheDocument();
  expect(within(section).queryByRole('button', { name: 'More plans' })).not.toBeInTheDocument();
});

test('only the most recent unfinished plan gets the primary Resume button', async () => {
  mockRoutes({
    'GET /sessions': jsonResponse(200, {
      items: [
        sessionFixture({ id: 's3', done: 4, content_title: 'Done talk' }),
        sessionFixture({ id: 's2', entry: 'both', done: 1, content_title: 'Newest' }),
        sessionFixture({ id: 's1', done: 1, content_title: 'Older' }),
      ],
      next_cursor: null,
    }),
  });
  renderWithProviders(<SessionsSection />);

  const section = await screen.findByRole('region', { name: 'Your plans' });
  const newest = within(section).getByRole('link', { name: 'Resume Newest' });
  const older = within(section).getByRole('link', { name: 'Resume Older' });
  expect(newest).toHaveAttribute('data-variant', 'primary');
  expect(older).toHaveAttribute('data-variant', 'secondary');
  expect(within(section).getByRole('link', { name: 'View Done talk' })).toHaveAttribute(
    'data-variant',
    'secondary',
  );
});

test('without any plan, the section is not shown', async () => {
  const { spy } = mockRoutes({
    'GET /sessions': jsonResponse(200, { items: [], next_cursor: null }),
  });
  const { container } = renderWithProviders(<SessionsSection />);
  await vi.waitFor(() => expect(spy).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test('a plan is deleted only after confirming, and leaves the list (FR-SH-17)', async () => {
  let deleted = false;
  const { calls } = mockRoutes({
    'GET /sessions': () =>
      jsonResponse(200, {
        items: deleted
          ? [sessionFixture({ id: 's1', content_title: 'Kept talk' })]
          : [
              sessionFixture({ id: 's2', done: 4, content_title: 'Old talk' }),
              sessionFixture({ id: 's1', content_title: 'Kept talk' }),
            ],
        next_cursor: null,
      }),
    'DELETE /sessions/s2': () => {
      deleted = true;
      return jsonResponse(202, { request_id: 'r1' });
    },
  });
  renderWithProviders(<SessionsSection />);

  const section = await screen.findByRole('region', { name: 'Your plans' });
  fireEvent.click(within(section).getByRole('button', { name: 'Delete plan Old talk' }));
  const dialog = screen.getByRole('dialog', { name: 'Delete this plan on Old talk?' });
  expect(dialog).toHaveTextContent(/recordings, marks and cards/);
  expect(within(dialog).getByRole('button', { name: 'Keep plan' })).toHaveFocus();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep plan' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(calls.some((call) => call.method === 'DELETE')).toBe(false);

  fireEvent.click(within(section).getByRole('button', { name: 'Delete plan Old talk' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete plan' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Plan deleted.');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(calls.find((call) => call.method === 'DELETE')?.body).toEqual({ confirm: true });
  await vi.waitFor(() =>
    expect(within(section).queryByText('Old talk', { selector: 'b' })).not.toBeInTheDocument(),
  );
  expect(within(section).getByText('Kept talk', { selector: 'b' })).toBeInTheDocument();
});

test('a refused plan deletion keeps the dialog open with the error and a retry', async () => {
  let attempts = 0;
  mockRoutes({
    'GET /sessions': jsonResponse(200, {
      items: [sessionFixture({ id: 's2', content_title: 'Old talk' })],
      next_cursor: null,
    }),
    'DELETE /sessions/s2': () => {
      attempts += 1;
      return attempts === 1
        ? jsonResponse(503, { code: 'unavailable', detail: 'Try again shortly.', status: 503 })
        : jsonResponse(202, { request_id: 'r1' });
    },
  });
  renderWithProviders(<SessionsSection />);

  fireEvent.click(await screen.findByRole('button', { name: 'Delete plan Old talk' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete plan' }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByRole('alert')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: /try again/i }));
  expect(await screen.findByRole('status')).toHaveTextContent('Plan deleted.');
  expect(attempts).toBe(2);
});
