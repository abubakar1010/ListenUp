import { act, fireEvent, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { Link, Route, Routes } from 'react-router';

import type { LiveEvent } from '../../events/useLiveEvents';
import { jsonResponse, mockApi, problem, renderWithProviders } from '../../test-utils';
import { ClipNotices } from './ClipNotices';
import { useClipNotices } from './useClipNotices';

afterEach(() => vi.restoreAllMocks());

const READY = {
  id: 'content-1',
  title: 'Morning news',
  source: 'upload',
  status: 'playable',
  duration_ms: 60_000,
  created_at: '2026-10-03T09:00:00Z',
  media_object_id: 'media-1',
  has_video: false,
  keep_video: false,
  error_code: null,
  error_detail: null,
  media_url: '/api/v1/media/media-1',
  peaks_url: '/api/v1/media/media-1/peaks',
};

const sender: { current: (event: LiveEvent) => void } = { current: () => undefined };

function send(event: LiveEvent) {
  sender.current(event);
}

function Harness() {
  const notices = useClipNotices();
  useEffect(() => {
    sender.current = notices.onEvent;
  });
  return (
    <>
      <Routes>
        <Route path="/library" element={<Link to="/sessions/s-1">Practise</Link>} />
        <Route path="/contents/:contentId" element={<h1>Clip page</h1>} />
        <Route path="/sessions/:sessionId" element={<Link to="/library">Leave</Link>} />
      </Routes>
      <ClipNotices notices={notices} />
    </>
  );
}

function ready(resourceId = 'content-1'): LiveEvent {
  return { id: 'h-1', type: 'content.ready', resourceId };
}

test('a clip that becomes ready elsewhere is announced politely without taking focus', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, READY) });
  renderWithProviders(<Harness />, { route: '/library' });
  const focused = document.activeElement;

  act(() => send(ready()));

  const text = await screen.findByText('“Morning news” is ready to practise.');
  expect(text.closest('[aria-live="polite"]')).not.toBeNull();
  expect(document.activeElement).toBe(focused);
  expect(screen.getByRole('link', { name: 'Open the clip' })).toHaveAttribute(
    'href',
    '/contents/content-1',
  );

  const dismiss = screen.getByRole('button', { name: 'Dismiss' });
  expect(dismiss).toHaveAccessibleDescription('\u201cMorning news\u201d is ready to practise.');
  fireEvent.click(dismiss);
  expect(screen.queryByText(/is ready to practise/)).not.toBeInTheDocument();
});

test('a failed clip is announced with a link to the reason', async () => {
  mockApi({
    '/contents/content-1': jsonResponse(200, {
      ...READY,
      status: 'failed',
      error_code: 'clip_too_short',
      media_url: null,
      peaks_url: null,
    }),
  });
  renderWithProviders(<Harness />, { route: '/library' });

  act(() => send(ready()));

  expect(await screen.findByText('“Morning news” could not be prepared.')).toBeVisible();
  expect(screen.getByRole('link', { name: 'See why' })).toHaveAttribute(
    'href',
    '/contents/content-1',
  );
});

test('a removed copy points at the clip the learner already has', async () => {
  mockApi({
    '/contents/content-2': problem(410, 'duplicate_upload', 'You already have this clip.', {
      existing_content_id: 'content-1',
      existing_title: 'Morning news',
    }),
  });
  renderWithProviders(<Harness />, { route: '/library' });

  act(() => send(ready('content-2')));

  expect(
    await screen.findByText(
      'You already have “Morning news”, so the copy you just added was not kept.',
    ),
  ).toBeVisible();
  expect(screen.getByRole('link', { name: 'Open it' })).toHaveAttribute(
    'href',
    '/contents/content-1',
  );
});

test("no notice shows on the clip's own page, which says it already", async () => {
  const fetch = mockApi({ '/contents/content-1': jsonResponse(200, READY) });
  renderWithProviders(<Harness />, { route: '/contents/content-1' });

  act(() => send(ready()));

  await act(async () => {});
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByText(/is ready to practise/)).not.toBeInTheDocument();
});

test('during practice a notice waits until the learner leaves the session', async () => {
  mockApi({ '/contents/content-1': jsonResponse(200, READY) });
  renderWithProviders(<Harness />, { route: '/sessions/s-1' });

  act(() => send(ready()));
  await act(async () => {});
  await act(async () => {});
  expect(screen.queryByText(/is ready to practise/)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('link', { name: 'Leave' }));

  expect(await screen.findByText('“Morning news” is ready to practise.')).toBeVisible();
});

test('progress events make no notice', async () => {
  const fetch = mockApi({ '/contents/content-1': jsonResponse(200, READY) });
  renderWithProviders(<Harness />, { route: '/library' });

  act(() => send({ id: 'h-2', type: 'job.progress', resourceId: 'content-1' }));

  await act(async () => {});
  expect(fetch).not.toHaveBeenCalled();
});
