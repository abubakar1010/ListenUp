import { fireEvent, screen, waitFor } from '@testing-library/react';

import { App } from '../../App';
import { jsonResponse, LEARNER, problem, renderWithProviders } from '../../test-utils';

const UNTIL = '2026-10-11T20:30:00Z';

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

/** Mocks the API by method and path; DELETE /me answers with `onDelete`. */
function mockAccount(onDelete: (body: unknown) => Response) {
  let deleted = false;
  const deletes: unknown[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    const method = init?.method ?? 'GET';
    if (path === '/me' && method === 'DELETE') {
      const body: unknown = JSON.parse(String(init?.body));
      deletes.push(body);
      const response = onDelete(body);
      deleted = response.ok;
      return response;
    }
    if (path === '/me/exports/latest') {
      return jsonResponse(200, { export: null });
    }
    if (path === '/me') {
      return deleted
        ? problem(401, 'not_signed_in', 'Sign in to continue.')
        : jsonResponse(200, LEARNER);
    }
    return problem(404, 'not_found', path);
  });
  return deletes;
}

async function enterPasswordAndOpenDialog(password = 'correct horse') {
  fireEvent.change(await screen.findByLabelText('Your password'), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Delete my account' }));
  return screen.findByRole('dialog', { name: 'Delete your account?' });
}

test('explains the grace period before anything happens', async () => {
  mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings' });

  expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Delete your account', level: 2 })).toBeVisible();
  expect(screen.getByText(/kept for 7 days/)).toBeInTheDocument();
  expect(screen.getByText(/sign in within that time and restore/)).toBeInTheDocument();
});

test('promises the grace period the server reports, not a fixed one', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    if (path === '/me') return jsonResponse(200, { ...LEARNER, deletion_grace_days: 14 });
    if (path === '/me/exports/latest') return jsonResponse(200, { export: null });
    return problem(404, 'not_found', path);
  });
  renderWithProviders(<App />, { route: '/settings' });

  expect(await screen.findByText(/kept for 14 days/)).toBeInTheDocument();
  expect(screen.queryByText(/7 days/)).not.toBeInTheDocument();
});

test('asks for the password before opening the confirmation', async () => {
  mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings' });

  fireEvent.click(await screen.findByRole('button', { name: 'Delete my account' }));

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Enter your password');
  expect(screen.getByLabelText('Your password')).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByLabelText('Your password')).toHaveFocus();
});

test('the confirmation starts on the safe action and can be cancelled', async () => {
  const deletes = mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings' });

  const dialog = await enterPasswordAndOpenDialog();

  expect(dialog).toHaveTextContent('signed out at once');
  expect(screen.getByRole('button', { name: 'Keep my account' })).toHaveFocus();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(deletes).toEqual([]);
});

test('deleting signs out and shows until when the account can be restored', async () => {
  const deletes = mockAccount(() =>
    jsonResponse(202, { deletion_scheduled_at: UNTIL, detail: 'Deleted.' }),
  );
  renderWithProviders(<App />, { route: '/settings' });

  await enterPasswordAndOpenDialog();
  fireEvent.click(
    screen
      .getAllByRole('button', { name: 'Delete my account' })
      .find((button) => button.closest('[role="dialog"]'))!,
  );

  expect(
    await screen.findByRole('heading', { name: 'Your account is deleted', level: 1 }),
  ).toBeInTheDocument();
  const date = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'full',
    timeStyle: 'short',
  }).format(new Date(UNTIL));
  expect(screen.getByText(date)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Go to sign in' })).toBeInTheDocument();
  expect(deletes).toEqual([{ password: 'correct horse', confirm: true }]);
});

test('a wrong password closes the dialog and marks the field', async () => {
  mockAccount(() => problem(403, 'wrong_password', 'The password is wrong.'));
  renderWithProviders(<App />, { route: '/settings' });

  await enterPasswordAndOpenDialog('not it');
  fireEvent.click(
    screen
      .getAllByRole('button', { name: 'Delete my account' })
      .find((button) => button.closest('[role="dialog"]'))!,
  );

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('alert')).toHaveTextContent('The password is wrong.');
  expect(screen.getByLabelText('Your password')).toHaveAttribute('aria-invalid', 'true');
  await waitFor(() => expect(screen.getByLabelText('Your password')).toHaveFocus());
});

test('another failure stays in the dialog with what to do next', async () => {
  mockAccount(() => problem(503, 'database_unavailable', 'The service is busy.'));
  renderWithProviders(<App />, { route: '/settings' });

  const dialog = await enterPasswordAndOpenDialog();
  fireEvent.click(
    screen
      .getAllByRole('button', { name: 'Delete my account' })
      .find((button) => button.closest('[role="dialog"]'))!,
  );

  expect(await screen.findByText('The service is busy.')).toBeInTheDocument();
  expect(dialog).toBeInTheDocument();
});
