import { act, fireEvent, screen, within } from '@testing-library/react';
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

test('a ready audio clip plays in the shared player (#198)', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, clip()) });
  const { container } = renderPage();

  expect(
    await screen.findByRole('heading', { name: 'Why cities plant street trees', level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByText('Ready to play.')).toHaveAttribute('role', 'status');
  expect(screen.getByText('03:20')).toBeInTheDocument();
  const audio = container.ownerDocument.querySelector('audio')!;
  expect(audio).toHaveAttribute('src', '/api/v1/media/media-1');
  expect(audio).toHaveAttribute('preload', 'metadata');
  expect(audio).not.toHaveAttribute('controls');
  for (const name of ['Back 5 seconds', 'Play', 'Replay segment']) {
    expect(screen.getByRole('button', { name })).toBeInTheDocument();
  }
  expect(screen.getByRole('slider', { name: 'Seek' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Speed' })).toBeInTheDocument();
  expect(screen.getByText('Whole clip')).toBeInTheDocument();
  expect(screen.queryByText(/replays?$/)).not.toBeInTheDocument();
  expect(document.title).toBe('Why cities plant street trees · ListenUp');
  expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library');
});

test('outside text fields, Space plays and [ slows down on the clip page (UX-07)', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  mockApi({ '/contents/content-1': jsonResponse(200, clip()) });
  const { container } = renderPage();
  await screen.findByRole('button', { name: 'Play' });
  const audio = container.ownerDocument.querySelector('audio')!;
  act(() => {
    audio.dispatchEvent(new Event('loadedmetadata'));
  });

  fireEvent.keyDown(document.body, { key: ' ', code: 'Space' });
  expect(play).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(document.body, { key: '[', code: 'BracketLeft' });
  expect(audio.playbackRate).toBe(0.9);
  // Keys typed into a field are text.
  const field = document.createElement('input');
  document.body.append(field);
  fireEvent.keyDown(field, { key: ' ', code: 'Space' });
  expect(play).toHaveBeenCalledTimes(1);
  field.remove();
});

test('a ready clip of unknown length keeps the browser player, with the focus ring', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, clip({ duration_ms: null })) });
  renderPage();

  const player = await screen.findByLabelText('Play Why cities plant street trees');
  expect(player.tagName).toBe('AUDIO');
  expect(player).toHaveAttribute('controls');
  expect(player.className).toContain('focus-visible:outline-focus-ring');
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
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
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

test('a clip in the queue says where it is and that the page updates', async () => {
  mockApi({
    '/contents/content-1': jsonResponse(
      200,
      clip({
        status: 'pending',
        stage: 'queued',
        queue_position: 1,
        duration_ms: null,
        media_url: null,
        peaks_url: null,
      }),
    ),
  });
  renderPage();

  const status = await screen.findByText(/^Waiting for your other clips/);
  expect(status).toHaveAttribute('role', 'status');
  expect(status).toHaveTextContent(
    'Waiting for your other clips: two of your clips are prepared at a time. It is 1st in line.',
  );
});

test('a copy of a clip the learner has links to that clip', async () => {
  mockApi({
    '/contents/content-1': problem(
      410,
      'duplicate_upload',
      'You already have this clip in your library, as \u201cMorning news\u201d, so this copy was not added. Open that clip to practise it.',
      { existing_content_id: 'content-0', existing_title: 'Morning news' },
    ),
  });
  renderPage();

  const alert = await screen.findByRole('alert');
  expect(within(alert).getByRole('heading', { level: 1 })).toHaveTextContent(
    'You already have this clip',
  );
  expect(alert).toHaveTextContent('so this copy was not added');
  expect(within(alert).getByRole('link', { name: 'Open Morning news' })).toHaveAttribute(
    'href',
    '/contents/content-0',
  );
});
