import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import AddClipPage from './AddClipPage';

const MB = 1024 * 1024;
const TARGET = {
  upload_id: 'up-1',
  url: 'http://storage.test/listenup/users/1/uploads/up-1.mp3?X-Amz-Signature=abc',
  method: 'PUT',
  headers: { 'Content-Type': 'audio/mpeg' },
  expires_at: '2026-10-03T10:00:00Z',
};
const ITEM = {
  id: 'content-1',
  title: 'street-trees-talk',
  source: 'upload',
  status: 'pending',
  duration_ms: null,
  created_at: '2026-10-03T09:00:00Z',
};
const USAGE = { used_bytes: 600 * MB, quota_bytes: 2048 * MB, max_file_bytes: 500 * MB };

/** A stand-in for XMLHttpRequest that the test drives by hand. */
class FakeXhr {
  static last: FakeXhr | null = null;
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  aborted = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ loaded, total, lengthComputable: true } as ProgressEvent);
  }
  finish(status = 200) {
    this.status = status;
    this.onload?.();
  }
}

type Call = { path: string; method: string; body: unknown };

/** Mocks the API by method and path, and records every call. */
function mockUploadApi(routes: Record<string, () => Response>) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const responder = routes[`${method} ${path}`];
    return responder ? responder() : problem(404, 'not_found', `No mock for ${method} ${path}.`);
  });
  return calls;
}

function file(name: string, size: number, type: string): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/library/add" element={<AddClipPage />} />
      <Route path="/library" element={<h1>Library</h1>} />
    </Routes>,
    { route: '/library/add' },
  );
}

function choose(f: File) {
  fireEvent.change(screen.getByLabelText('Choose a file'), { target: { files: [f] } });
}

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
  FakeXhr.last = null;
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('a file is uploaded with progress, confirmed and shown in the library', async () => {
  const calls = mockUploadApi({
    'GET /uploads/usage': () => jsonResponse(200, USAGE),
    'POST /uploads': () => jsonResponse(201, TARGET),
    'POST /contents': () => jsonResponse(201, ITEM),
  });
  renderPage();
  expect(await screen.findByText(/of 2.0 GB used by your uploads/)).toHaveTextContent(
    '600 MB of 2.0 GB used by your uploads',
  );

  choose(file('street-trees-talk.mp3', 50 * MB, 'audio/mpeg'));

  await waitFor(() => expect(FakeXhr.last).not.toBeNull());
  const xhr = FakeXhr.last!;
  expect(xhr.method).toBe('PUT');
  expect(xhr.url).toBe(TARGET.url);
  expect(xhr.headers).toEqual({ 'Content-Type': 'audio/mpeg' });
  expect(calls.find((c) => c.path === '/uploads')?.body).toEqual({
    filename: 'street-trees-talk.mp3',
    content_type: 'audio/mpeg',
    size_bytes: 50 * MB,
  });

  act(() => xhr.progress(25 * MB, 50 * MB));
  const bar = screen.getByRole('progressbar', { name: 'street-trees-talk.mp3' });
  expect(bar).toHaveAttribute('aria-valuenow', '50');
  expect(screen.getByText('50%')).toBeInTheDocument();
  expect(screen.getByText('Upload 50%')).toBeInTheDocument(); // the polite live region

  act(() => xhr.progress(50 * MB, 50 * MB));
  expect(screen.queryByRole('button', { name: 'Cancel upload' })).not.toBeInTheDocument();
  act(() => xhr.finish(200));

  expect(await screen.findByRole('heading', { name: 'Library' })).toBeInTheDocument();
  expect(calls.find((c) => c.path === '/contents')?.body).toEqual({ upload_id: 'up-1' });
});

test('cancelling stops the upload and leaves nothing behind', async () => {
  const calls = mockUploadApi({
    'GET /uploads/usage': () => jsonResponse(200, USAGE),
    'POST /uploads': () => jsonResponse(201, TARGET),
    'DELETE /uploads/up-1': () => new Response(null, { status: 204 }),
  });
  renderPage();
  choose(file('talk.mp3', 50 * MB, 'audio/mpeg'));
  await waitFor(() => expect(FakeXhr.last).not.toBeNull());
  act(() => FakeXhr.last!.progress(10 * MB, 50 * MB));

  const cancel = screen.getByRole('button', { name: 'Cancel upload' });
  cancel.focus();
  fireEvent.click(cancel);

  expect(FakeXhr.last!.aborted).toBe(true);
  expect(await screen.findByText('Upload cancelled.')).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  await waitFor(() =>
    expect(calls).toContainEqual({ path: '/uploads/up-1', method: 'DELETE', body: undefined }),
  );
  expect(calls.some((c) => c.path === '/contents')).toBe(false);
});

test('a file over 500 MB is refused before anything is sent', async () => {
  const calls = mockUploadApi({ 'GET /uploads/usage': () => jsonResponse(200, USAGE) });
  renderPage();

  choose(file('full-movie.mp4', 600 * MB, 'video/mp4'));

  const alert = await screen.findByRole('alert');
  expect(within(alert).getByRole('heading')).toHaveTextContent('full-movie.mp4 is too large');
  expect(alert).toHaveTextContent('It is 600 MB. The limit is 500 MB per file.');
  expect(calls.filter((c) => c.method !== 'GET')).toEqual([]);
  expect(FakeXhr.last).toBeNull();
});

test('a file of another type is refused before anything is sent', async () => {
  const calls = mockUploadApi({ 'GET /uploads/usage': () => jsonResponse(200, USAGE) });
  renderPage();

  choose(file('notes.pdf', MB, 'application/pdf'));

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent("notes.pdf can't be used");
  expect(alert).toHaveTextContent('Choose an MP3, M4A, WAV, MP4, MOV or WEBM file.');
  expect(calls.filter((c) => c.method !== 'GET')).toEqual([]);
});

test('a refusal from the server is shown with what to do next', async () => {
  mockUploadApi({
    'GET /uploads/usage': () => jsonResponse(200, USAGE),
    'POST /uploads': () =>
      problem(422, 'storage_full', 'You have used 1.9 GB of 2.0 GB, and this file is 184 MB.'),
  });
  renderPage();

  choose(file('talk.m4a', 184 * MB, ''));

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Something needs fixing');
  expect(alert).toHaveTextContent('You have used 1.9 GB of 2.0 GB');
});

test('a dropped file is uploaded too', async () => {
  mockUploadApi({
    'GET /uploads/usage': () => jsonResponse(200, USAGE),
    'POST /uploads': () => jsonResponse(201, TARGET),
  });
  renderPage();

  const zone = screen.getByText('Drag an audio or video file here').parentElement!;
  fireEvent.drop(zone, { dataTransfer: { files: [file('talk.wav', MB, 'audio/wav')] } });

  await waitFor(() => expect(FakeXhr.last).not.toBeNull());
  expect(screen.getByRole('progressbar', { name: 'talk.wav' })).toBeInTheDocument();
});

test('a lost connection during the upload can be retried', async () => {
  mockUploadApi({
    'GET /uploads/usage': () => jsonResponse(200, USAGE),
    'POST /uploads': () => jsonResponse(201, TARGET),
    'DELETE /uploads/up-1': () => new Response(null, { status: 204 }),
  });
  renderPage();
  choose(file('talk.mp3', MB, 'audio/mpeg'));
  await waitFor(() => expect(FakeXhr.last).not.toBeNull());
  const first = FakeXhr.last!;

  act(() => first.onerror?.());

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('We could not reach ListenUp');
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(FakeXhr.last).not.toBe(first));
});
