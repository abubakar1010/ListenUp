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

test('without any plan, the section is not shown', async () => {
  const { spy } = mockRoutes({
    'GET /sessions': jsonResponse(200, { items: [], next_cursor: null }),
  });
  const { container } = renderWithProviders(<SessionsSection />);
  await vi.waitFor(() => expect(spy).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
