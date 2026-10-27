import { fireEvent, screen } from '@testing-library/react';
import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import MarksPage from './MarksPage';

it('loads successive pages and links each mark at its absolute source time', async () => {
  const mark = {
    id: 'm1',
    session_id: 's1',
    source: 'manual',
    status: 'confirmed',
    at_ms: 11000,
    source_url: '/contents/clip-1?at_ms=11000',
    created_at: '2026-10-26T10:00:00Z',
    note: 'Listen closely',
  };
  mockRoutes({
    'GET /marks': jsonResponse(200, { marks: [mark], next_cursor: 'next' }),
    'GET /marks?cursor=next': jsonResponse(200, {
      marks: [
        {
          ...mark,
          id: 'm2',
          session_id: 's2',
          source: 'dictation',
          at_ms: 30000,
          source_url: '/contents/clip-2?at_ms=30000',
          note: null,
        },
      ],
      next_cursor: null,
    }),
  });
  renderWithProviders(<MarksPage />);
  expect(await screen.findByText('Listen closely')).toBeVisible();
  expect(screen.getByRole('link', { name: 'Open source at 11.0 seconds' })).toHaveAttribute(
    'href',
    mark.source_url,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Load more marks' }));
  expect(await screen.findByRole('link', { name: 'Open source at 30.0 seconds' })).toHaveAttribute(
    'href',
    '/contents/clip-2?at_ms=30000',
  );
  expect(
    screen
      .getAllByRole('link', { name: 'Open practice session' })
      .map((link) => link.getAttribute('href')),
  ).toEqual(['/sessions/s1', '/sessions/s2']);
  expect(screen.queryByRole('button', { name: 'Load more marks' })).not.toBeInTheDocument();
});
it('shows empty and failed list states', async () => {
  mockRoutes({ 'GET /marks': jsonResponse(200, { marks: [], next_cursor: null }) });
  const view = renderWithProviders(<MarksPage />);
  expect(await screen.findByText('No saved marks yet.')).toBeVisible();
  view.unmount();
  mockRoutes({ 'GET /marks': problem(503, 'unavailable', 'Marks unavailable') });
  renderWithProviders(<MarksPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Marks unavailable');
});
