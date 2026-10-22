import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { jsonResponse, problem } from '../../test-utils';
import { type Call, mockRoutes } from '../session/testApi';
import type { DiffItem } from './api';
import { DictationMarks } from './DictationMarks';

const PATH = '/dictation/attempts/attempt-1/marks';

const missing = (index: number, word: string): DiffItem => ({
  index,
  status: 'missing',
  word,
  typed: '',
});
const correct = (index: number, word: string): DiffItem => ({
  index,
  status: 'correct',
  word,
  typed: word,
});

// Five missed words, none next to another.
const FIVE_MISSED: DiffItem[] = [
  correct(0, 'Cities'),
  missing(1, 'plant'),
  correct(2, 'street'),
  missing(3, 'trees'),
  correct(4, 'to'),
  missing(5, 'cool'),
  correct(6, 'the'),
  missing(7, 'air'),
  correct(8, 'in'),
  missing(9, 'summer.'),
];
// "to cool" missed together, then "summer." alone.
const A_RUN: DiffItem[] = [
  correct(3, 'trees'),
  missing(4, 'to'),
  { index: 5, status: 'wrong', word: 'cool', typed: 'cold' },
  correct(6, 'the'),
  missing(9, 'summer.'),
];

interface Stored {
  id: string;
  word_from: number;
  word_to: number;
}
const stored = (mark: Stored) => ({
  ...mark,
  at_ms: 1000 * (mark.word_from + 1),
  source: 'dictation',
  status: 'suggested',
});

/** The marks API as the server answers it: words already marked give back their mark. */
function fakeMarks(initial: Stored[] = []) {
  const marks = [...initial];
  const routes = mockRoutes({
    [`GET ${PATH}`]: () => jsonResponse(200, { marks: marks.map(stored) }),
    [`POST ${PATH}`]: (call: Call) => {
      const body = call.body as { marks: Stored[] };
      const answer = body.marks.map((mark) => {
        const same = marks.find(
          (m) => m.word_from === mark.word_from && m.word_to === mark.word_to,
        );
        if (same) return same;
        marks.push(mark);
        return mark;
      });
      return jsonResponse(200, { marks: answer.map(stored) });
    },
  });
  const posts = () => routes.calls.filter((call) => call.method === 'POST');
  return { marks, posts };
}

function renderMarks(items: DiffItem[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DictationMarks attemptId="attempt-1" items={items} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const addButton = (phrase: string) =>
  screen.findByRole('button', { name: `Add “${phrase}” to marks` });
const added = (phrase: string) =>
  screen.findByRole('button', { name: `“${phrase}” added to marks` });

afterEach(() => vi.restoreAllMocks());

test('adding 2 of 5 missed words sends those two and shows them as added', async () => {
  const { marks, posts } = fakeMarks();
  renderMarks(FIVE_MISSED);

  fireEvent.click(await addButton('plant'));
  await added('plant');
  fireEvent.click(await addButton('cool'));
  await added('cool');

  expect(posts().map((call) => (call.body as { marks: Stored[] }).marks)).toEqual([
    [{ id: expect.any(String), word_from: 1, word_to: 1 }],
    [{ id: expect.any(String), word_from: 5, word_to: 5 }],
  ]);
  expect(marks.map((m) => m.word_from)).toEqual([1, 5]);
  for (const other of ['trees', 'air', 'summer.']) expect(await addButton(other)).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Added “cool” to your marks.');
});

test('words added before, here or in Transcript, show as added after a reload', async () => {
  const { posts } = fakeMarks([{ id: 'm-1', word_from: 3, word_to: 3 }]);
  renderMarks(FIVE_MISSED);

  const button = await added('trees');
  fireEvent.click(button);

  expect(button).toHaveAttribute('aria-disabled', 'true');
  expect(posts()).toHaveLength(0);
});

test('a run of missed words is added as one mark, or one word of it alone', async () => {
  const { posts } = fakeMarks();
  renderMarks(A_RUN);

  const run = await screen.findByRole('listitem', { name: '“to cool”' });
  fireEvent.click(within(run).getByRole('button', { name: 'Add “to cool” to marks' }));
  await added('to cool');
  fireEvent.click(within(run).getByRole('button', { name: 'Add “cool” to marks' }));
  await added('cool');

  expect(posts().map((call) => (call.body as { marks: Stored[] }).marks[0])).toMatchObject([
    { word_from: 4, word_to: 5 },
    { word_from: 5, word_to: 5 },
  ]);
});

test('add all adds every run that is not added yet in one request', async () => {
  const { posts } = fakeMarks([{ id: 'm-1', word_from: 9, word_to: 9 }]);
  renderMarks(A_RUN);

  fireEvent.click(await screen.findByRole('button', { name: 'Add all' }));

  expect(await screen.findByRole('button', { name: 'All added' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  expect(posts()).toHaveLength(1);
  expect((posts()[0].body as { marks: Stored[] }).marks).toMatchObject([
    { word_from: 4, word_to: 5 },
  ]);
  expect(screen.getByRole('status')).toHaveTextContent('Added 1 mark to your marks.');
});

test('every action is a button the keyboard reaches, and focus stays on it once added', async () => {
  fakeMarks();
  renderMarks(FIVE_MISSED);

  const button = await addButton('air');
  expect(button.tagName).toBe('BUTTON');
  expect(button).not.toHaveAttribute('tabindex', '-1');
  button.focus();
  fireEvent.click(button); // Enter and Space activate a focused native button

  expect(await added('air')).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Add all' }).tagName).toBe('BUTTON');
});

test('a failed add says so, keeps the words addable and retries with the same mark id', async () => {
  let fail = true;
  const ids: string[] = [];
  mockRoutes({
    [`GET ${PATH}`]: jsonResponse(200, { marks: [] }),
    [`POST ${PATH}`]: (call: Call) => {
      const [mark] = (call.body as { marks: Stored[] }).marks;
      ids.push(mark.id);
      if (fail) return problem(503, 'service_unavailable', 'The service is busy.');
      return jsonResponse(200, { marks: [stored(mark)] });
    },
  });
  renderMarks(FIVE_MISSED);

  fireEvent.click(await addButton('plant'));
  expect(await screen.findByRole('alert')).toHaveTextContent('The service is busy.');
  expect(await addButton('plant')).toBeVisible();

  fail = false;
  fireEvent.click(screen.getByRole('button', { name: /try again/i }));

  await added('plant');
  expect(ids).toHaveLength(2);
  expect(ids[1]).toBe(ids[0]);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('a diff with nothing missed or wrong offers nothing to add', async () => {
  fakeMarks();
  renderMarks([correct(0, 'Cities'), correct(1, 'plant')]);

  await act(async () => undefined);
  expect(screen.queryByRole('heading', { name: 'Add to your marks' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('a failed read of the marks shows the problem with a retry', async () => {
  mockRoutes({ [`GET ${PATH}`]: problem(500, 'internal_error', 'Something broke.') });
  renderMarks(FIVE_MISSED);

  expect(await screen.findByRole('alert')).toHaveTextContent('Something broke.');
  expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
});
