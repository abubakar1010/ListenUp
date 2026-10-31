import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { attemptFixture, blindStepFixture } from '../blind/fixtures';
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
  expect(
    await screen.findByText('No pausing. Listen once, all the way through.'),
  ).toBeInTheDocument();
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
  expect(
    within(screen.getByRole('region', { name: 'Transcript' })).getByText(/Opening your Transcript/),
  );
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

test('a recorded Shadow completion shows unavailable feedback after reload', async () => {
  mockRoutes({
    'GET /sessions/session-1': jsonResponse(200, sessionFixture({ done: 4 })),
    'GET /contents/clip-1': jsonResponse(200, { media_url: '/original' }),
    'GET /sessions/session-1/shadow/rounds': jsonResponse(200, {
      segment: { start_ms: 10000, end_ms: 70000 },
      rounds: [1, 2, 3].map((round) => ({
        id: `round-${round}`,
        round,
        recording_available: true,
      })),
    }),
  });
  renderSession();
  expect(await screen.findByText('All 4 steps finished')).toBeInTheDocument();
  expect(screen.getByText('Feedback unavailable.')).toBeInTheDocument();
  expect(screen.queryByText("The clip's player will show here.")).not.toBeInTheDocument();
  for (const round of [1, 2, 3]) {
    expect(await screen.findByLabelText(`Your recording of round ${round}`)).toHaveAttribute(
      'src',
      `/api/v1/shadow/rounds/round-${round}/recording`,
    );
    expect(screen.getByLabelText(`Original, round ${round} segment`)).toHaveAttribute(
      'src',
      '/original#t=10,70',
    );
  }
  expect(screen.queryByRole('button', { name: /Start round/ })).not.toBeInTheDocument();
});

test('completion remains visible when replay data cannot load and offers retry', async () => {
  let failed = true;
  mockRoutes({
    'GET /sessions/session-1': jsonResponse(200, sessionFixture({ done: 4 })),
    'GET /contents/clip-1': () =>
      failed
        ? problem(503, 'unavailable', 'Original unavailable.')
        : jsonResponse(200, { media_url: '/original' }),
    'GET /sessions/session-1/shadow/rounds': () =>
      failed
        ? problem(503, 'unavailable', 'Recordings unavailable.')
        : jsonResponse(200, { segment: { start_ms: 0, end_ms: 60000 }, rounds: [] }),
  });
  renderSession();
  expect(await screen.findByText('Recordings unavailable.')).toBeInTheDocument();
  expect(screen.getByText('Original unavailable.')).toBeInTheDocument();
  expect(screen.getByText('All 4 steps finished')).toBeInTheDocument();
  failed = false;
  for (const button of screen.getAllByRole('button', { name: /Try again/i }))
    fireEvent.click(button);
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});

test('a finished plan with Shadow skipped has no player placeholder or replay', async () => {
  const { calls } = mockRoutes({
    'GET /sessions/session-1': jsonResponse(200, sessionFixture({ done: 4, skipped: ['shadow'] })),
  });
  renderSession();
  expect(await screen.findByText('All 4 steps finished')).toBeInTheDocument();
  expect(screen.queryByText("The clip's player will show here.")).not.toBeInTheDocument();
  expect(screen.queryByText('Feedback unavailable.')).not.toBeInTheDocument();
  expect(calls.some((c) => c.path.includes('/shadow/'))).toBe(false);
});

// UX shared rule (focus order on practice screens), WCAG 2.4.3 (#98): arriving at a step
// puts focus on its heading. The control that moved the plan on is gone with its step.
test('arriving_at_the_next_step_focuses_its_heading', async () => {
  let submitted = false;
  const gist = 'This is the idea. Here is another detail. I heard this too.';
  const attempt = () =>
    attemptFixture({
      listen_complete: true,
      status: submitted ? 'submitted' : 'active',
      gist_text: submitted ? gist : null,
    });
  mockRoutes({
    'GET /sessions/session-1': () =>
      jsonResponse(200, sessionFixture({ entry: 'blind', done: submitted ? 1 : 0 })),
    'GET /sessions/session-1/blind': () => jsonResponse(200, blindStepFixture(attempt())),
    'POST /blind/attempts/attempt-1/gist': () => {
      submitted = true;
      return jsonResponse(201, { attempt: attempt(), open_step: 'transcript', session_version: 1 });
    },
    'GET /gists/attempt-1/grade': jsonResponse(200, { status: 'pending', wait_ms: 60_000 }),
    'GET /sessions/session-1/transcript': jsonResponse(200, {
      session_id: 'session-1',
      passage: sessionFixture().passage,
      media_url: '/api/v1/media/test',
      lines: [],
    }),
    'GET /sessions/session-1/marks': jsonResponse(200, { marks: [] }),
  });
  renderSession();
  fireEvent.change(await screen.findByRole('textbox', { name: 'Your gist' }), {
    target: { value: gist },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));
  const next = await screen.findByRole('button', { name: 'Continue to Transcript' });
  next.focus();
  fireEvent.click(next);

  const heading = await screen.findByRole('heading', { level: 1, name: /^Transcript:/ });
  await waitFor(() => expect(heading).toHaveFocus());
});

test('a step that places focus itself keeps it on arrival', async () => {
  mockRoutes({ 'GET /sessions/session-1': jsonResponse(200, sessionFixture({ done: 2 })) });
  renderSession();
  // Card focuses its own heading when it opens; the session leaves that alone.
  const own = await screen.findByRole('heading', { level: 2, name: 'Keep a sound you missed' });
  await waitFor(() => expect(own).toHaveFocus());
});

// The arriving step may swap its loading screen for its content, replacing the focused
// heading; the arrival focus follows to the new heading (#98).
test('arrival focus follows the heading when the step finishes loading', async () => {
  let submitted = false;
  let releaseTranscript: () => void = () => undefined;
  const transcriptReady = new Promise<void>((resolve) => (releaseTranscript = resolve));
  const gist = 'This is the idea. Here is another detail. I heard this too.';
  const attempt = () =>
    attemptFixture({
      listen_complete: true,
      status: submitted ? 'submitted' : 'active',
      gist_text: submitted ? gist : null,
    });
  mockRoutes({
    'GET /sessions/session-1': () =>
      jsonResponse(200, sessionFixture({ entry: 'blind', done: submitted ? 1 : 0 })),
    'GET /sessions/session-1/blind': () => jsonResponse(200, blindStepFixture(attempt())),
    'POST /blind/attempts/attempt-1/gist': () => {
      submitted = true;
      return jsonResponse(201, { attempt: attempt(), open_step: 'transcript', session_version: 1 });
    },
    'GET /gists/attempt-1/grade': jsonResponse(200, { status: 'pending', wait_ms: 60_000 }),
    'GET /sessions/session-1/transcript': async () => {
      await transcriptReady;
      return jsonResponse(200, {
        session_id: 'session-1',
        passage: sessionFixture().passage,
        media_url: '/api/v1/media/test',
        lines: [],
      });
    },
    'GET /sessions/session-1/marks': jsonResponse(200, { marks: [] }),
  });
  renderSession();
  fireEvent.change(await screen.findByRole('textbox', { name: 'Your gist' }), {
    target: { value: gist },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));
  const next = await screen.findByRole('button', { name: 'Continue to Transcript' });
  next.focus();
  fireEvent.click(next);
  const pending = await screen.findByRole('heading', { level: 1, name: /^Transcript:/ });
  await waitFor(() => expect(pending).toHaveFocus());

  releaseTranscript();
  await screen.findByText(/Transcript can't be skipped/);
  await waitFor(() => {
    const heading = screen.getByRole('heading', { level: 1, name: /^Transcript:/ });
    expect(heading).not.toBe(pending);
    expect(heading).toHaveFocus();
  });
});
