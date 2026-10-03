import { act, fireEvent, screen, waitFor } from '@testing-library/react';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { mockRoutes } from '../session/testApi';
import { attemptFixture } from './fixtures';
import { GistForm } from './GistForm';

const TWO = 'Cities plant trees on streets. Shade cools the air.';
const THREE = `${TWO} Roots can break pipes.`;
const SUBMIT = 'POST /blind/attempts/attempt-1/gist';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function renderForm() {
  return renderWithProviders(<GistForm sessionId="session-1" attemptId="attempt-1" />);
}

function type(text: string) {
  fireEvent.change(screen.getByRole('textbox', { name: 'Your gist' }), {
    target: { value: text },
  });
}

test('the count follows the text and says what is missing', () => {
  mockRoutes({});
  renderForm();

  expect(screen.getByText('0 of 3 sentences. Write 3 more.')).toBeInTheDocument();
  type(TWO);
  expect(screen.getByText('2 of 3 sentences. Write one more.')).toHaveAttribute(
    'aria-live',
    'polite',
  );
  type(THREE);
  expect(screen.getByText('3 sentences. Ready to submit.')).toBeInTheDocument();
});

test('two sentences are not sent; the message takes focus', async () => {
  const { calls } = mockRoutes({});
  renderForm();
  type(TWO);

  const submit = screen.getByRole('button', { name: 'Submit gist' });
  expect(submit).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(submit);

  const message = await screen.findByRole('alert');
  expect(message).toHaveTextContent('2 of 3 sentences. Write one more, then submit.');
  await waitFor(() => expect(message).toHaveFocus());
  expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
});

test('three sentences are submitted once, with an Idempotency-Key', async () => {
  const { calls } = mockRoutes({
    [SUBMIT]: jsonResponse(201, {
      attempt: attemptFixture({ status: 'submitted', gist_text: THREE }),
      open_step: 'transcript',
      session_version: 1,
    }),
  });
  renderForm();
  type(THREE);

  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));

  await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
  const post = calls.find((c) => c.method === 'POST')!;
  expect(post.body).toEqual({ text: THREE });
  expect(post.headers['Idempotency-Key']).toBe('gist-attempt-1');
});

test('the server refusing the gist shows its reason', async () => {
  mockRoutes({
    [SUBMIT]: problem(
      409,
      'listen_incomplete',
      'Listen to the whole passage before you write the gist.',
    ),
  });
  renderForm();
  type(THREE);

  fireEvent.click(screen.getByRole('button', { name: 'Submit gist' }));

  expect(
    await screen.findByText('Listen to the whole passage before you write the gist.'),
  ).toBeInTheDocument();
});

test('the draft is kept on this device and comes back', async () => {
  vi.useFakeTimers();
  mockRoutes({});
  const { unmount } = renderForm();
  type(TWO);
  await act(() => vi.advanceTimersByTimeAsync(600));
  vi.useRealTimers();

  expect(screen.getByText('Draft saved')).toBeInTheDocument();
  unmount();
  renderForm();
  expect(screen.getByRole('textbox', { name: 'Your gist' })).toHaveValue(TWO);
});
