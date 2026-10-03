import { screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from './fixtures';
import SessionPage from './SessionPage';
import { mockRoutes } from './testApi';

afterEach(() => vi.restoreAllMocks());

function renderSession(id = 'session-1') {
  return renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: `/sessions/${id}` },
  );
}

function stepItems() {
  const list = screen.getByRole('list', { name: 'Plan steps' });
  return within(list).getAllByRole('listitem');
}

test('a new plan of both shows "Step 1 of 5" with Blind open', async () => {
  mockRoutes({ 'GET /sessions/session-1': jsonResponse(200, sessionFixture({ entry: 'both' })) });
  renderSession();

  expect(await screen.findByText('Step 1 of 5')).toBeInTheDocument();
  const items = stepItems();
  expect(items.map((li) => li.textContent)).toEqual([
    'Blind, nowNow',
    'Dictation, locked',
    'Transcript, locked',
    'Card, locked',
    'Shadow, locked',
  ]);
  expect(items[0]).toHaveAttribute('aria-current', 'step');
  expect(items.filter((li) => li.hasAttribute('aria-current'))).toHaveLength(1);
  expect(
    screen.getByRole('heading', { name: 'Blind: Why cities plant street trees', level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByText('Passage 02:10 to 04:40')).toBeInTheDocument();
  expect(screen.getByText('Listen once. No pausing, no rewinding.')).toBeInTheDocument();
});

test('finished steps are marked done and the open step is current', async () => {
  mockRoutes({
    'GET /sessions/session-1': jsonResponse(200, sessionFixture({ entry: 'both', done: 2 })),
  });
  renderSession();

  expect(await screen.findByText('Step 3 of 5')).toBeInTheDocument();
  const items = stepItems();
  expect(items.map((li) => li.dataset.status)).toEqual([
    'done',
    'done',
    'open',
    'locked',
    'locked',
  ]);
  expect(items[0]).toHaveTextContent('Blind, done');
  expect(items[2]).toHaveAttribute('aria-current', 'step');
  expect(within(screen.getByRole('region', { name: 'Transcript' })).getByText(/3 · Transcript/));
});

test('a completed plan says so and offers another plan on the clip', async () => {
  mockRoutes({
    'GET /sessions/session-1': jsonResponse(
      200,
      sessionFixture({ done: 4, skipped: ['card', 'shadow'] }),
    ),
  });
  renderSession();

  expect(await screen.findByText('All 4 steps finished')).toBeInTheDocument();
  expect(screen.getByText('Skipped: Card and Shadow.')).toBeInTheDocument();
  expect(stepItems().filter((li) => li.hasAttribute('aria-current'))).toHaveLength(0);
  expect(screen.getByRole('link', { name: 'Start another plan on this clip' })).toHaveAttribute(
    'href',
    '/contents/clip-1/plan',
  );
});

test("another learner's or a missing session shows a clear error", async () => {
  mockRoutes({
    'GET /sessions/nope': problem(404, 'session_not_found', 'There is no such session.'),
  });
  renderSession('nope');

  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('There is no such session.');
  expect(within(alert).getByRole('link', { name: 'Go to your library' })).toBeInTheDocument();
});
