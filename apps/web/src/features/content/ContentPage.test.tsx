import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, mockApi, problem, renderWithProviders } from '../../test-utils';
import ContentPage from './ContentPage';
import type { ContentDetail } from './useContent';

afterEach(() => vi.restoreAllMocks());

function clip(overrides: Partial<ContentDetail> = {}): ContentDetail {
  return {
    id: 'content-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: 200_000,
    created_at: '2026-10-03T09:00:00Z',
    media_object_id: 'media-1',
    has_video: false,
    keep_video: false,
    error_code: null,
    error_detail: null,
    media_url: '/api/v1/media/media-1',
    peaks_url: '/api/v1/media/media-1/peaks',
    ...overrides,
  };
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/contents/:contentId" element={<ContentPage />} />
      <Route path="/library" element={<h1>Library</h1>} />
    </Routes>,
    { route: '/contents/content-1' },
  );
}

test('a ready clip plays from the media URL with labelled native controls', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, clip()) });
  renderPage();

  expect(
    await screen.findByRole('heading', { name: 'Why cities plant street trees', level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByText('Ready to play.')).toHaveAttribute('role', 'status');
  expect(screen.getByText('03:20')).toBeInTheDocument();
  const player = screen.getByLabelText('Play Why cities plant street trees');
  expect(player.tagName).toBe('AUDIO');
  expect(player).toHaveAttribute('src', '/api/v1/media/media-1');
  expect(player).toHaveAttribute('controls');
  expect(player).toHaveAttribute('preload', 'metadata');
  expect(document.title).toBe('Why cities plant street trees · ListenUp');
  expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library');
});

test('a clip that kept its video plays in a video player', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, clip({ has_video: true })) });
  renderPage();

  const player = await screen.findByLabelText('Play Why cities plant street trees');
  expect(player.tagName).toBe('VIDEO');
});

test('a clip still processing says so and has no player yet', async () => {
  mockApi({
    '/contents/content-1': jsonResponse(
      200,
      clip({ status: 'pending', duration_ms: null, media_url: null, peaks_url: null }),
    ),
  });
  renderPage();

  const status = await screen.findByText(
    'Processing. This page updates by itself when the clip is ready.',
  );
  expect(status).toHaveAttribute('role', 'status');
  expect(screen.queryByLabelText(/^Play /)).not.toBeInTheDocument();
});

test('a clip still processing is checked again until it is ready', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let calls = 0;
    mockApi({
      '/contents/content-1': () => {
        calls += 1;
        return jsonResponse(
          200,
          calls === 1 ? clip({ status: 'pending', media_url: null, peaks_url: null }) : clip(),
        );
      },
    });
    renderPage();
    expect(await screen.findByText(/^Processing\./)).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(5000);

    expect(await screen.findByText('Ready to play.')).toBeInTheDocument();
    expect(screen.getByLabelText('Play Why cities plant street trees')).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

test('a failed clip shows the reason', async () => {
  mockApi({
    '/contents/content-1': jsonResponse(
      200,
      clip({
        status: 'failed',
        error_code: 'unsupported_media',
        error_detail: "This file isn't audio or video we can play, whatever its name says.",
        media_url: null,
        peaks_url: null,
      }),
    ),
  });
  renderPage();

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('This clip could not be prepared');
  expect(alert).toHaveTextContent("This file isn't audio or video we can play");
  expect(screen.getByRole('link', { name: 'Add another file' })).toHaveAttribute(
    'href',
    '/library/add',
  );
  expect(screen.queryByLabelText(/^Play /)).not.toBeInTheDocument();
});

test('a clip that is not in the library leads back to it', async () => {
  mockApi({
    '/contents/content-1': problem(
      404,
      'content_not_found',
      'This clip is not in your library. Go back to the library.',
    ),
  });
  renderPage();

  expect(
    await screen.findByRole('heading', { name: 'We could not find this', level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('This clip is not in your library.');
  expect(screen.getByRole('link', { name: 'Go to your library' })).toHaveAttribute(
    'href',
    '/library',
  );
});
