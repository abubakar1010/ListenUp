import { fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, mockApi, problem, renderWithProviders } from '../../test-utils';
import LibraryPage from './LibraryPage';
import type { LibraryItem } from './useLibrary';

afterEach(() => vi.restoreAllMocks());

function item(n: number, overrides: Partial<LibraryItem> = {}): LibraryItem {
  return {
    id: `item-${n}`,
    title: `Clip ${n}`,
    source: 'upload',
    status: 'playable',
    duration_ms: 200_000,
    created_at: '2026-10-03T09:00:00Z',
    last_session_status: null,
    ...overrides,
  };
}

function renderLibrary() {
  return renderWithProviders(
    <Routes>
      <Route path="/library" element={<LibraryPage />} />
      <Route path="/library/add" element={<h1>Add a clip</h1>} />
    </Routes>,
    { route: '/library' },
  );
}

test('an empty library leads to adding the first clip', async () => {
  mockApi({ '/library/contents': jsonResponse(200, { items: [], next_cursor: null }) });
  renderLibrary();

  expect(
    await screen.findByRole('heading', { name: 'Add your first clip', level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByText('MP3, M4A, WAV, MP4, MOV or WEBM, up to 500 MB per file.')).toBeVisible();

  fireEvent.click(screen.getByRole('link', { name: 'Upload a file' }));
  expect(screen.getByRole('heading', { name: 'Add a clip' })).toBeInTheDocument();
});

test('clips show title, source, length and status', async () => {
  mockApi({
    '/library/contents': jsonResponse(200, {
      items: [
        item(1, { title: 'Why cities plant street trees', status: 'pending', duration_ms: null }),
        item(2, {
          title: 'Podcast ep. 41',
          duration_ms: 2_285_000,
          last_session_status: 'completed',
        }),
        item(3, { title: 'Friends clip', status: 'failed' }),
      ],
      next_cursor: null,
    }),
  });
  renderLibrary();

  const list = await screen.findByRole('list');
  const rows = within(list).getAllByRole('listitem');
  expect(rows).toHaveLength(3);
  expect(rows[0]).toHaveTextContent('Why cities plant street trees');
  expect(rows[0]).toHaveTextContent('Upload · Added 3 Oct');
  expect(rows[0]).toHaveTextContent('Processing');
  expect(rows[1]).toHaveTextContent('Upload · 38:05 · Added 3 Oct');
  expect(rows[1]).toHaveTextContent('Ready');
  expect(rows[1]).toHaveTextContent('Last session: Completed');
  expect(rows[2]).toHaveTextContent('Could not be processed');
  expect(screen.getByRole('link', { name: 'Add a clip' })).toHaveAttribute('href', '/library/add');
  expect(
    within(rows[0]).getByRole('link', { name: 'Why cities plant street trees' }),
  ).toHaveAttribute('href', '/contents/item-1');
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
});

test('"Load more" fetches the next page with the cursor', async () => {
  const fetchMock = mockApi({
    '/library/contents': jsonResponse(200, {
      items: Array.from({ length: 20 }, (_, n) => item(30 - n)),
      next_cursor: 'cursor/20=',
    }),
    '/library/contents?cursor=cursor%2F20%3D': jsonResponse(200, {
      items: Array.from({ length: 10 }, (_, n) => item(10 - n)),
      next_cursor: null,
    }),
  });
  renderLibrary();

  expect(await screen.findAllByRole('listitem')).toHaveLength(20);
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('Clip 1')).toBeInTheDocument();
  expect(screen.getAllByRole('listitem')).toHaveLength(30);
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test('a library that cannot load says why and offers a retry', async () => {
  let calls = 0;
  mockApi({
    '/library/contents': () => {
      calls += 1;
      return calls === 1
        ? problem(503, 'service_unavailable', 'The service is busy.')
        : jsonResponse(200, { items: [item(1)], next_cursor: null });
    },
  });
  renderLibrary();

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('The service is busy.');
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));

  expect(await screen.findByText('Clip 1')).toBeInTheDocument();
});
