import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import type { Session } from './api';
import { sessionFixture } from './fixtures';
import SessionPage from './SessionPage';
import { mockRoutes } from './testApi';

afterEach(() => vi.restoreAllMocks());

function renderSession() {
  return renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: '/sessions/session-1' },
  );
}

/** GET answers with whatever `current` is; writes may replace it. */
function serve(initial: Session, writes: Record<string, (body: unknown) => Response>) {
  let current = initial;
  const routes: Record<string, (call: { body: unknown }) => Response> = {
    'GET /sessions/session-1': () => jsonResponse(200, current),
  };
  for (const [route, write] of Object.entries(writes)) {
    routes[route] = ({ body }) => {
      const response = write(body);
      if (response.ok)
        void response
          .clone()
          .json()
          .then((s: Session) => (current = s));
      return response;
    };
  }
  return mockRoutes(routes);
}

// Changing the entry (#49)

test('before Transcript, changing Blind to both turns "Step 1 of 4" into "Step 1 of 5"', async () => {
  const { calls } = serve(sessionFixture({ entry: 'blind' }), {
    'PATCH /sessions/session-1/entry': () =>
      jsonResponse(200, sessionFixture({ entry: 'both', version: 1 })),
  });
  renderSession();

  expect(await screen.findByText('Step 1 of 4')).toBeInTheDocument();
  const toggle = screen.getByRole('button', { name: 'Change entry' });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const panel = screen.getByRole('region', { name: 'Change how you start' });
  expect(within(panel).getByRole('checkbox', { name: /Blind/ })).toBeChecked();
  expect(within(panel).getByText('Your plan becomes: 4 steps')).toBeInTheDocument();
  expect(within(panel).getByRole('button', { name: 'Save change' })).toBeDisabled();

  fireEvent.click(within(panel).getByRole('checkbox', { name: /Dictation/ }));
  expect(within(panel).getByText('Your plan becomes: 5 steps')).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole('button', { name: 'Save change' }));

  expect(await screen.findByText('Step 1 of 5')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Change how you start' })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Change entry' })).toHaveFocus());
  expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ entry: 'both', version: 0 });
});

test('a finished entry exercise is kept and cannot be cleared', async () => {
  serve(sessionFixture({ entry: 'both', done: 1 }), {});
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Change entry' }));
  const blind = screen.getByRole('checkbox', { name: /Blind/ });
  expect(blind).toBeChecked();
  expect(blind).toBeDisabled();
  expect(screen.getByText('· done, kept')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('checkbox', { name: /Dictation/ }));
  expect(screen.getByText('Your plan becomes: 4 steps')).toBeInTheDocument();
});

test('once Transcript has started, the entry is locked', async () => {
  serve(sessionFixture({ entry: 'blind', done: 1 }), {});
  renderSession();

  expect(await screen.findByText('Step 2 of 4')).toBeInTheDocument();
  expect(screen.getByText('Entry locked')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Change entry' })).not.toBeInTheDocument();
});

test('a change the server refuses shows why and loads the session again', async () => {
  let gets = 0;
  const { calls } = mockRoutes({
    'GET /sessions/session-1': () => {
      gets += 1;
      return jsonResponse(
        200,
        gets === 1
          ? sessionFixture({ entry: 'blind' })
          : sessionFixture({ entry: 'blind', done: 1 }),
      );
    },
    'PATCH /sessions/session-1/entry': () =>
      problem(
        409,
        'entry_locked',
        'The entry choice cannot change: the entry choice is locked once Transcript has opened.',
      ),
  });
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Change entry' }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Dictation/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Save change' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('locked once Transcript has opened');
  expect(await screen.findByText('Entry locked')).toBeInTheDocument();
  expect(screen.getByText('Step 2 of 4')).toBeInTheDocument();
  expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThanOrEqual(2);
});

// Skipping (#49)

test('Transcript has no skip', async () => {
  serve(sessionFixture({ entry: 'dictation', done: 1 }), {});
  renderSession();

  expect(await screen.findByText('Step 2 of 4')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Skip/ })).not.toBeInTheDocument();
  expect(screen.getByText(/Transcript can't be skipped/)).toBeInTheDocument();
});

test('skipping Card asks first; cancelling keeps the step open', async () => {
  const { calls } = serve(sessionFixture({ done: 2 }), {});
  renderSession();

  const skip = await screen.findByRole('button', { name: 'Skip Card' });
  skip.focus();
  fireEvent.click(skip);

  const dialog = screen.getByRole('dialog', { name: 'Skip Card?' });
  expect(dialog).toHaveAttribute('aria-modal', 'true');
  expect(dialog).toHaveAccessibleDescription(/you can't make cards for this session/);
  const safe = within(dialog).getByRole('button', { name: 'Make a card' });
  expect(safe).toHaveFocus();

  // Focus stays in the dialog.
  fireEvent.keyDown(safe, { key: 'Tab' });
  expect(within(dialog).getByRole('button', { name: 'Skip Card' })).toHaveFocus();
  fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
  expect(safe).toHaveFocus();

  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(() => expect(skip).toHaveFocus());
  expect(screen.getByText('Step 3 of 4')).toBeInTheDocument();

  fireEvent.click(skip);
  fireEvent.click(screen.getByRole('button', { name: 'Make a card' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(calls.some((c) => c.method === 'POST')).toBe(false);
});

test('confirming skips Card and opens Shadow', async () => {
  const { calls } = serve(sessionFixture({ done: 2 }), {
    'POST /sessions/session-1/steps/card/skip': () =>
      jsonResponse(200, sessionFixture({ done: 3, skipped: ['card'] })),
  });
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Skip Card' }));
  const dialog = screen.getByRole('dialog', { name: 'Skip Card?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Skip Card' }));

  expect(await screen.findByText('Step 4 of 4')).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ confirmed: true, version: 2 });
  const card = within(screen.getByRole('list', { name: 'Plan steps' })).getAllByRole('listitem')[2];
  expect(card).toHaveTextContent('Card, skipped');
  expect(screen.getByRole('button', { name: 'Skip Shadow' })).toBeInTheDocument();
});

test('skipping Shadow after Card was done completes the plan (D12)', async () => {
  serve(sessionFixture({ done: 3 }), {
    'POST /sessions/session-1/steps/shadow/skip': () =>
      jsonResponse(200, sessionFixture({ done: 4, skipped: ['shadow'] })),
  });
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Skip Shadow' }));
  fireEvent.click(screen.getByRole('button', { name: 'Skip Shadow and finish' }));

  expect(await screen.findByText('All 4 steps finished')).toBeInTheDocument();
  expect(screen.getByText('Plan complete', { selector: 'p' })).toBeInTheDocument();
  expect(screen.getByText('Skipped: Shadow.')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('main')).toHaveFocus());
});

test('a refused skip is shown inside the dialog', async () => {
  serve(sessionFixture({ done: 2 }), {
    'POST /sessions/session-1/steps/card/skip': () =>
      problem(
        409,
        'session_changed',
        'The session changed in another request. Reload and try again.',
      ),
  });
  renderSession();

  fireEvent.click(await screen.findByRole('button', { name: 'Skip Card' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Skip Card' }));

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'The session changed in another request.',
  );
});
