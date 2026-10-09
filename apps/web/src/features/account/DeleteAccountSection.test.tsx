import { fireEvent, screen, waitFor } from '@testing-library/react';

import { App } from '../../App';
import { jsonResponse, LEARNER, problem, renderWithProviders } from '../../test-utils';

const UNTIL = '2026-10-11T20:30:00Z';
const SUMMARY = { clips: 3, practice_sessions: 8, cards: 2, recordings: 1 };

beforeEach(() => {
  document.cookie = 'listenup_csrf=token-123';
});
afterEach(() => vi.restoreAllMocks());

/** Mocks the account endpoints; DELETE /me answers with `onDelete`. */
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
    if (path === '/me/deletion-summary') return jsonResponse(200, SUMMARY);
    if (path === '/me/exports/latest') return jsonResponse(200, { export: null });
    if (path === '/me') {
      return deleted
        ? problem(401, 'not_signed_in', 'Sign in to continue.')
        : jsonResponse(200, LEARNER);
    }
    return problem(404, 'not_found', path);
  });
  return deletes;
}

async function openConfirmation(password = 'correct horse') {
  fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));
  const field = await screen.findByLabelText('Your password');
  fireEvent.change(field, { target: { value: password } });
  return field;
}

function acknowledgeAndDelete() {
  fireEvent.click(screen.getByRole('checkbox', { name: /I understand this can't be undone/i }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete my account' }));
}

test('settings links to a separate deletion page', async () => {
  mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings' });

  expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument();
  expect(screen.getByText(/restore it by signing in during the 7 days/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Review account deletion' }));

  expect(await screen.findByText('Step 1 of 2 · Check what will be deleted')).toBeInTheDocument();
});

test('step one shows counts, the permanent date and an export offer', async () => {
  mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings/delete-account' });

  expect(await screen.findByText('3 clips in your library')).toBeInTheDocument();
  expect(screen.getByText('8 practice sessions')).toBeInTheDocument();
  expect(screen.getByText('2 saved cards')).toBeInTheDocument();
  expect(screen.getByText('1 recording')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'download your data' })).toHaveAttribute(
    'href',
    '/settings#data-export',
  );
  expect(screen.getByText(/deleted for good on/)).toBeInTheDocument();
});

test('step two repeats the date and requires both confirmations', async () => {
  mockAccount(() => jsonResponse(500, {}));
  renderWithProviders(<App />, { route: '/settings/delete-account' });
  const field = await openConfirmation('');

  fireEvent.click(screen.getByRole('button', { name: 'Delete my account' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Enter your password');
  expect(field).toHaveFocus();

  fireEvent.change(field, { target: { value: 'correct horse' } });
  fireEvent.click(screen.getByRole('button', { name: 'Delete my account' }));
  expect(screen.getByRole('checkbox')).toHaveFocus();
  expect(
    screen.getByText(/My account will be switched off now and deleted for good on/),
  ).toBeVisible();
});

test('deleting signs out and shows until when the account can be restored', async () => {
  const deletes = mockAccount(() =>
    jsonResponse(202, { deletion_scheduled_at: UNTIL, detail: 'Deleted.' }),
  );
  renderWithProviders(<App />, { route: '/settings/delete-account' });

  await openConfirmation();
  acknowledgeAndDelete();

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

test('a wrong password stays on confirmation and marks the field', async () => {
  mockAccount(() => problem(403, 'wrong_password', 'The password is wrong.'));
  renderWithProviders(<App />, { route: '/settings/delete-account' });

  await openConfirmation('not it');
  acknowledgeAndDelete();

  expect(await screen.findByRole('alert')).toHaveTextContent('The password is wrong.');
  expect(screen.getByLabelText('Your password')).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByLabelText('Your password')).toHaveFocus();
  expect(screen.getByText('Step 2 of 2 · Confirm deletion')).toBeInTheDocument();
});

test('another failure stays on confirmation with what to do next', async () => {
  mockAccount(() => problem(503, 'database_unavailable', 'The service is busy.'));
  renderWithProviders(<App />, { route: '/settings/delete-account' });

  await openConfirmation();
  acknowledgeAndDelete();

  expect(await screen.findByText('The service is busy.')).toBeInTheDocument();
  expect(screen.getByText('Step 2 of 2 · Confirm deletion')).toBeInTheDocument();
});

/** Just enough of EventSource to send the page one event. */
class FakeEventSource {
  static latest: FakeEventSource | null = null;
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeEventSource.latest = this;
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {}

  emit(type: string, resourceId: string) {
    const event = new MessageEvent<string>(type, {
      data: JSON.stringify({ resource_id: resourceId }),
    });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

test('its own account.disabled event does not send the deleting tab to sign in', async () => {
  vi.stubGlobal('EventSource', FakeEventSource);
  let answer: (response: Response) => void = () => {};
  let meCalls = 0;
  let deleted = false;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).replace(/^\/api\/v1/, '');
    if (path === '/me' && init?.method === 'DELETE') {
      deleted = true;
      return new Promise<Response>((resolve) => (answer = resolve));
    }
    if (path === '/me/deletion-summary') return jsonResponse(200, SUMMARY);
    if (path === '/me') {
      meCalls += 1;
      return deleted
        ? problem(401, 'not_signed_in', 'Sign in to continue.')
        : jsonResponse(200, LEARNER);
    }
    return problem(404, 'not_found', path);
  });
  try {
    renderWithProviders(<App />, { route: '/settings/delete-account' });
    await openConfirmation();
    acknowledgeAndDelete();
    await waitFor(() => expect(deleted).toBe(true));
    const before = meCalls;

    FakeEventSource.latest!.emit('account.disabled', LEARNER.id);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(meCalls).toBe(before);
    expect(screen.getByText('Step 2 of 2 · Confirm deletion')).toBeInTheDocument();
    answer(jsonResponse(202, { deletion_scheduled_at: UNTIL, detail: 'Deleted.' }));
    expect(
      await screen.findByRole('heading', { name: 'Your account is deleted', level: 1 }),
    ).toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
  }
});
