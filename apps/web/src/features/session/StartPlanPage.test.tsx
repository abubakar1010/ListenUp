import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import type { LibraryItem } from '../library/useLibrary';
import { sessionFixture } from './fixtures';
import StartPlanPage from './StartPlanPage';
import { mockRoutes } from './testApi';

afterEach(() => vi.restoreAllMocks());

function clip(overrides: Partial<LibraryItem> = {}): LibraryItem {
  return {
    id: 'clip-1',
    title: 'Why cities plant street trees',
    source: 'upload',
    status: 'playable',
    duration_ms: 600_000,
    created_at: '2026-10-03T09:00:00Z',
    last_session_status: null,
    ...overrides,
  };
}

function library(item: LibraryItem) {
  return jsonResponse(200, { items: [item], next_cursor: null });
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/contents/:contentId/plan" element={<StartPlanPage />} />
      <Route path="/sessions/:sessionId" element={<h1>Session page</h1>} />
    </Routes>,
    { route: '/contents/clip-1/plan' },
  );
}

const startButton = () => screen.getByRole('button', { name: 'Start plan' });

test('the whole clip and Blind are chosen first; Both gives 5 steps with Blind first', async () => {
  const { calls } = mockRoutes({
    'GET /library/contents?limit=50': library(clip()),
    'POST /sessions': () => jsonResponse(201, sessionFixture({ id: 'new-1', entry: 'both' })),
  });
  renderPage();

  expect(await screen.findByRole('radio', { name: /Whole clip · 10:00/ })).toBeChecked();
  expect(screen.getByText('10 minutes selected')).toBeInTheDocument();
  const blind = screen.getByRole('checkbox', { name: /Blind/ });
  const dictation = screen.getByRole('checkbox', { name: /Dictation/ });
  expect(blind).toBeChecked();
  expect(blind).toHaveAccessibleDescription(/Listen once to the whole passage/);
  expect(dictation).toHaveAccessibleDescription(/Type every word you hear/);
  expect(screen.getByText('Your plan: 4 steps')).toBeInTheDocument();

  fireEvent.click(dictation);
  expect(screen.getByText('Your plan: 5 steps')).toBeInTheDocument();
  const preview = screen.getByText('Your plan: 5 steps').parentElement!;
  expect(
    within(preview)
      .getAllByRole('listitem')
      .map((li) => li.textContent),
  ).toEqual(['Blind', 'Dictation', 'Transcript', 'Card', 'Shadow']);

  fireEvent.click(startButton());

  expect(await screen.findByRole('heading', { name: 'Session page' })).toBeInTheDocument();
  const post = calls.find((c) => c.method === 'POST')!;
  expect(post.body).toEqual({
    content_id: 'clip-1',
    passage: { start_ms: 0, end_ms: 600_000 },
    entry: 'both',
  });
  expect(post.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
});

test('a part is typed as start and end in mm:ss and checked against 30 s to 15 min', async () => {
  const { calls } = mockRoutes({
    'GET /library/contents?limit=50': library(clip()),
    'POST /sessions': () => jsonResponse(201, sessionFixture({ id: 'new-1' })),
  });
  renderPage();

  fireEvent.click(await screen.findByRole('radio', { name: /A part of it/ }));
  const start = screen.getByRole('textbox', { name: 'Start' });
  const end = screen.getByRole('textbox', { name: 'End' });

  fireEvent.change(start, { target: { value: '02:10' } });
  fireEvent.change(end, { target: { value: '02:25' } });
  fireEvent.click(startButton());
  expect(end).toHaveAttribute('aria-invalid', 'true');
  expect(end).toHaveAccessibleDescription(
    'This part is 15 seconds. A part needs at least 30 seconds.',
  );
  expect(end).toHaveFocus();

  fireEvent.change(end, { target: { value: '11:00' } });
  fireEvent.click(startButton());
  expect(end).toHaveAccessibleDescription('The end is after the end of the clip (10:00).');

  fireEvent.change(end, { target: { value: '4:40' } });
  expect(end).not.toHaveAttribute('aria-invalid');
  expect(screen.getByText('2 minutes 30 seconds selected')).toBeInTheDocument();
  fireEvent.click(startButton());

  await screen.findByRole('heading', { name: 'Session page' });
  expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({
    passage: { start_ms: 130_000, end_ms: 280_000 },
    entry: 'blind',
  });
});

test('a clip over 15 minutes cannot be used whole; its first 15 minutes are suggested', async () => {
  mockRoutes({ 'GET /library/contents?limit=50': library(clip({ duration_ms: 2_285_000 })) });
  renderPage();

  const whole = await screen.findByRole('radio', { name: /Whole clip · 38:05/ });
  expect(whole).toBeDisabled();
  expect(whole).toHaveAccessibleDescription(
    'Too long to use whole. Choose a part of 15 minutes or less.',
  );
  expect(screen.getByRole('radio', { name: /A part of it/ })).toBeChecked();
  expect(screen.getByRole('textbox', { name: 'Start' })).toHaveValue('00:00');
  expect(screen.getByRole('textbox', { name: 'End' })).toHaveValue('15:00');

  fireEvent.change(screen.getByRole('textbox', { name: 'End' }), { target: { value: '16:00' } });
  fireEvent.click(startButton());
  expect(screen.getByRole('textbox', { name: 'End' })).toHaveAccessibleDescription(
    'This part is 16:00 long. A part can be 15 minutes at most.',
  );
});

test('with nothing ticked, the plan does not start and says why', async () => {
  const { calls } = mockRoutes({ 'GET /library/contents?limit=50': library(clip()) });
  renderPage();

  fireEvent.click(await screen.findByRole('checkbox', { name: /Blind/ }));
  expect(screen.getByText('Your plan: tick Blind, Dictation or both.')).toBeInTheDocument();
  fireEvent.click(startButton());

  expect(screen.getByText('Tick Blind, Dictation or both.')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: /Blind/ })).toHaveFocus();
  expect(calls.some((c) => c.method === 'POST')).toBe(false);
});

test('a clip that is still being prepared cannot start a plan yet', async () => {
  mockRoutes({
    'GET /library/contents?limit=50': library(clip({ status: 'pending', duration_ms: null })),
  });
  renderPage();

  expect(
    await screen.findByText(
      'This clip is still being prepared. You can start a plan as soon as it is ready.',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start plan' })).not.toBeInTheDocument();
});

test('a refusal is shown, and a retry of the same plan reuses its Idempotency-Key', async () => {
  let posts = 0;
  const { calls } = mockRoutes({
    'GET /library/contents?limit=50': library(clip()),
    'POST /sessions': () => {
      posts += 1;
      return posts === 1
        ? problem(503, 'service_unavailable', 'The service is busy.')
        : jsonResponse(201, sessionFixture({ id: 'new-1' }));
    },
  });
  renderPage();

  fireEvent.click(await screen.findByRole('button', { name: 'Start plan' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The service is busy.');
  fireEvent.click(startButton());

  await screen.findByRole('heading', { name: 'Session page' });
  const keys = calls.filter((c) => c.method === 'POST').map((c) => c.headers['Idempotency-Key']);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test('a clip that is not in the library is reported', async () => {
  mockRoutes({
    'GET /library/contents?limit=50': jsonResponse(200, { items: [], next_cursor: null }),
  });
  renderPage();

  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent('There is no such clip in your library.'),
  );
});
