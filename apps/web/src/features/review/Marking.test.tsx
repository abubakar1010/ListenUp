import { act, fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router';

import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import SessionPage from '../session/SessionPage';
import { mockRoutes, type Call } from '../session/testApi';
import type { SavedMark } from './markSync';

/** Marking a word or phrase in Transcript (#58; FR-TR-2, NFR-PERF-3, NFR-REL-1, UI-4). */

const SESSION = sessionFixture({ entry: 'dictation', done: 1 });
const MARKS = `/sessions/${SESSION.id}/marks`;
const DATA = {
  session_id: SESSION.id,
  passage: SESSION.passage,
  media_url: '/api/v1/media/media-1',
  lines: [
    {
      index: 0,
      start_ms: 131000,
      end_ms: 133000,
      words: [
        { index: 0, text: 'Hello', start_ms: 131000, end_ms: 132000 },
        { index: 1, text: 'world.', start_ms: 132000, end_ms: 133000 },
      ],
    },
    {
      index: 1,
      start_ms: 140125,
      end_ms: 142000,
      words: [{ index: 2, text: 'Again.', start_ms: 140125, end_ms: 142000 }],
    },
  ],
};

function serverMark(values: Partial<SavedMark> & { id: string }): SavedMark {
  return {
    session_id: SESSION.id,
    word_from: 0,
    word_to: 0,
    at_ms: 131000,
    note: null,
    source: 'manual',
    status: 'confirmed',
    created_at: '2026-10-19T10:00:00Z',
    ...values,
  };
}

/** A server that keeps the marks it is sent, like the real one. */
function markServer(initial: SavedMark[] = []) {
  const marks = new Map(initial.map((mark) => [mark.id, mark]));
  const created = (call: Call) => {
    const body = call.body as {
      id: string;
      word_from: number;
      word_to: number;
      note: string | null;
    };
    const mark = serverMark({
      ...body,
      at_ms: DATA.lines.flatMap((line) => line.words)[body.word_from]!.start_ms,
    });
    marks.set(mark.id, mark);
    return jsonResponse(201, mark);
  };
  return { marks, created };
}

function renderMarking(routes: Parameters<typeof mockRoutes>[0] = {}, initial: SavedMark[] = []) {
  const server = markServer(initial);
  const mocked = mockRoutes({
    [`GET /sessions/${SESSION.id}`]: jsonResponse(200, SESSION),
    [`GET /sessions/${SESSION.id}/transcript`]: jsonResponse(200, DATA),
    [`GET /sessions/${SESSION.id}/dictation/attempt`]: problem(404, 'attempt_not_found', 'None.'),
    [`GET ${MARKS}`]: () => jsonResponse(200, { marks: [...server.marks.values()] }),
    [`POST ${MARKS}`]: server.created,
    ...routes,
  });
  renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionPage />} />
    </Routes>,
    { route: `/sessions/${SESSION.id}` },
  );
  return { ...mocked, server };
}

async function ready() {
  const word = await screen.findByRole('button', { name: 'Jump to Hello' });
  fireEvent.loadedMetadata(document.querySelector('audio')!);
  return word;
}
const word = (text: string) => screen.getByRole('button', { name: `Jump to ${text}` });
const panel = () => screen.getByRole('region', { name: 'Mark words' });
const sent = (calls: Call[], method: string) =>
  calls.filter((call) => call.method === method && call.path.startsWith(MARKS));
async function afterDebounce() {
  await act(() => vi.advanceTimersByTimeAsync(2000));
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.useFakeTimers({ shouldAdvanceTime: true });
  localStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  localStorage.clear();
});

test('one_click_marks_the_chosen_word_at_once_and_saves_it_after_the_debounce', async () => {
  const { calls } = renderMarking();
  await ready();
  fireEvent.click(word('world.'));
  expect(within(panel()).getByText('“world.”')).toBeInTheDocument();
  fireEvent.click(within(panel()).getByRole('button', { name: 'Mark' }));
  // Shown at once, announced, and kept on this device before any request.
  expect(word('world.')).toHaveAccessibleDescription('Marked');
  expect(screen.getByText('Mark added: world., 02:12.')).toBeInTheDocument();
  expect(localStorage.getItem(`listenup:marks:${SESSION.id}`)).toContain('"op":"create"');
  expect(sent(calls, 'POST')).toEqual([]);
  await afterDebounce();
  const [post] = sent(calls, 'POST');
  expect(post!.body).toEqual({ id: expect.any(String), word_from: 1, word_to: 1, note: null });
  expect(within(panel()).getByText('Marks saved', { exact: false })).toBeInTheDocument();
  expect(localStorage.getItem(`listenup:marks:${SESSION.id}`)).toBeNull();
});

test('a_phrase_is_selected_with_shift_arrows_and_marked_with_the_m_key', async () => {
  const { calls } = renderMarking();
  const hello = await ready();
  hello.focus();
  fireEvent.keyDown(hello, { key: 'ArrowRight' });
  expect(word('world.')).toHaveFocus();
  fireEvent.keyDown(word('world.'), { key: 'ArrowLeft' });
  expect(hello).toHaveFocus();
  fireEvent.keyDown(hello, { key: 'ArrowRight', shiftKey: true });
  expect(word('world.')).toHaveFocus();
  expect(within(panel()).getByText('“Hello world.”')).toBeInTheDocument();
  expect(hello).toHaveAccessibleDescription('Selected');
  fireEvent.keyDown(word('world.'), { key: 'm' });
  expect(hello).toHaveAccessibleDescription('Marked');
  expect(word('world.')).toHaveAccessibleDescription('Marked');
  expect(screen.getByText('Mark added: Hello world., 02:11.')).toBeInTheDocument();
  expect(word('world.')).toHaveFocus();
  await afterDebounce();
  expect(sent(calls, 'POST')[0]!.body).toMatchObject({ word_from: 0, word_to: 1 });
});

test('arrows_stop_at_the_ends_and_escape_clears_the_selection', async () => {
  renderMarking();
  const hello = await ready();
  hello.focus();
  fireEvent.keyDown(hello, { key: 'ArrowLeft' });
  expect(hello).toHaveFocus();
  fireEvent.keyDown(hello, { key: 'ArrowLeft', shiftKey: true });
  expect(within(panel()).getByText('“Hello”')).toBeInTheDocument();
  fireEvent.keyDown(hello, { key: 'Escape' });
  expect(within(panel()).queryByRole('button', { name: 'Mark' })).not.toBeInTheDocument();
  word('Again.').focus();
  fireEvent.keyDown(word('Again.'), { key: 'ArrowRight' });
  expect(word('Again.')).toHaveFocus();
  // Other keys and modified M keep their usual meaning.
  fireEvent.keyDown(word('Again.'), { key: 'm', ctrlKey: true });
  expect(word('Again.')).not.toHaveAccessibleDescription('Marked');
});

test('shift_click_and_the_add_word_buttons_grow_the_selection_on_touch_and_mouse', async () => {
  renderMarking();
  await ready();
  fireEvent.click(word('world.'));
  fireEvent.click(within(panel()).getByRole('button', { name: 'Add previous word' }));
  expect(within(panel()).getByText('“Hello world.”')).toBeInTheDocument();
  fireEvent.click(within(panel()).getByRole('button', { name: 'Add next word' }));
  expect(within(panel()).getByText('“Hello world. Again.”')).toBeInTheDocument();
  fireEvent.click(word('Hello'));
  fireEvent.click(word('Again.'), { shiftKey: true });
  expect(within(panel()).getByText('“Hello world. Again.”')).toBeInTheDocument();
});

test('saved_marks_come_back_after_a_reload', async () => {
  renderMarking({}, [serverMark({ id: 'm1', word_from: 0, word_to: 1, note: 'linking' })]);
  await ready();
  expect(word('Hello')).toHaveAccessibleDescription('Marked');
  expect(word('world.')).toHaveAccessibleDescription('Marked');
  expect(word('Again.')).not.toHaveAccessibleDescription('Marked');
  // Choosing a marked word selects its mark and opens its note.
  fireEvent.click(word('world.'));
  expect(within(panel()).getByText('“Hello world.”')).toBeInTheDocument();
  expect(within(panel()).getByLabelText('Note (optional)')).toHaveValue('linking');
});

test('unsent_marks_survive_a_reload_and_a_lost_connection', async () => {
  localStorage.setItem(
    `listenup:marks:${SESSION.id}`,
    JSON.stringify({
      ops: [
        { op: 'create', mark: { id: 'kept', word_from: 2, word_to: 2, at_ms: 140125, note: null } },
      ],
    }),
  );
  let failing = true;
  const { calls, server } = renderMarking({
    [`POST ${MARKS}`]: (call) => {
      if (failing) throw new TypeError('Failed to fetch');
      return markServer().created(call);
    },
  });
  await ready();
  expect(word('Again.')).toHaveAccessibleDescription('Marked');
  await afterDebounce();
  expect(within(panel()).getByText('Offline. Saved on this device.')).toBeInTheDocument();
  expect(localStorage.getItem(`listenup:marks:${SESSION.id}`)).toContain('kept');
  failing = false;
  await act(async () => {
    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(sent(calls, 'POST').map((call) => (call.body as { id: string }).id)).toEqual([
    'kept',
    'kept',
  ]);
  expect(within(panel()).getByText('Marks saved', { exact: false })).toBeInTheDocument();
  expect(server.marks.size).toBe(0); // the mock answered from its own copy
});

test('a_note_is_saved_and_a_mark_can_be_removed', async () => {
  const mark = serverMark({ id: 'm1', word_from: 2, word_to: 2, at_ms: 140125 });
  const { calls } = renderMarking(
    {
      [`PATCH ${MARKS}/m1`]: (call) => jsonResponse(200, { ...mark, ...(call.body as object) }),
      [`DELETE ${MARKS}/m1`]: new Response(null, { status: 204 }),
    },
    [mark],
  );
  await ready();
  fireEvent.click(word('Again.'));
  const note = within(panel()).getByLabelText('Note (optional)');
  fireEvent.change(note, { target: { value: '  sounds like again  ' } });
  fireEvent.click(within(panel()).getByRole('button', { name: 'Save note' }));
  await afterDebounce();
  expect(sent(calls, 'PATCH')[0]!.body).toEqual({ note: 'sounds like again' });
  fireEvent.click(within(panel()).getByRole('button', { name: 'Remove mark' }));
  expect(word('Again.')).not.toHaveAccessibleDescription('Marked');
  expect(screen.getByText('Mark removed.')).toBeInTheDocument();
  await afterDebounce();
  expect(sent(calls, 'DELETE')).toHaveLength(1);
});

test('the_note_is_also_saved_when_the_field_loses_focus_and_m_opens_it', async () => {
  const mark = serverMark({ id: 'm1' });
  const { calls } = renderMarking(
    { [`PATCH ${MARKS}/m1`]: (call) => jsonResponse(200, { ...mark, ...(call.body as object) }) },
    [mark],
  );
  const hello = await ready();
  hello.focus();
  fireEvent.keyDown(hello, { key: 'M' });
  const note = within(panel()).getByLabelText('Note (optional)');
  expect(note).toHaveFocus();
  fireEvent.change(note, { target: { value: '' } });
  fireEvent.blur(note);
  fireEvent.change(note, { target: { value: 'weak form' } });
  fireEvent.blur(note);
  await afterDebounce();
  expect(sent(calls, 'PATCH').map((call) => call.body)).toEqual([{ note: 'weak form' }]);
});

test('a_refused_mark_is_taken_back_with_the_reason', async () => {
  renderMarking({
    [`POST ${MARKS}`]: problem(422, 'mark_too_long', 'Mark a word or a short phrase.'),
  });
  await ready();
  fireEvent.click(word('Hello'));
  fireEvent.click(within(panel()).getByRole('button', { name: 'Mark' }));
  await afterDebounce();
  expect(word('Hello')).not.toHaveAccessibleDescription('Marked');
  expect(
    within(panel()).getByText(/Not saved\. Mark a word or a short phrase\./),
  ).toBeInTheDocument();
});

test('the_marks_load_error_offers_a_retry', async () => {
  let fail = true;
  renderMarking({
    [`GET ${MARKS}`]: () =>
      fail
        ? problem(503, 'service_unavailable', 'Try again soon.')
        : jsonResponse(200, { marks: [] }),
  });
  expect(await screen.findByText('Try again soon.')).toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: /try again/i }));
  expect(await screen.findByRole('button', { name: 'Jump to Hello' })).toBeInTheDocument();
});
