import { fireEvent, screen, within, waitFor } from '@testing-library/react';
import { jsonResponse, problem, renderWithProviders } from '../../test-utils';
import { sessionFixture } from '../session/fixtures';
import { mockRoutes } from '../session/testApi';
import { CardScreen } from './CardScreen';

const session = sessionFixture({ done: 2 });
const mark = {
  id: 'mark-1',
  session_id: session.id,
  word_from: 0,
  word_to: 1,
  at_ms: 11000,
  note: null,
  source: 'manual',
  status: 'confirmed',
  created_at: '2026-10-23T00:00:00Z',
};
const card = {
  audio_status: 'ready' as string,
  id: 'card-1',
  session_id: session.id,
  slot: 1,
  mark_id: mark.id,
  written_form: 'could have',
  heard_form: 'kuduv',
  at_ms: 11000,
  content_id: session.content_id,
  source_url: '/contents/clip-1?at_ms=11000',
  created_at: '2026-10-23T00:00:00Z',
};
const path = `/sessions/${session.id}/cards`;
const listPath = `/cards?session_id=${session.id}`;
beforeEach(() => vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {}));
afterEach(() => vi.restoreAllMocks());
function setup(cards = [] as (typeof card)[], extraRoutes: Parameters<typeof mockRoutes>[0] = {}) {
  const saved = [...cards];
  const routes = mockRoutes({
    [`GET /sessions/${session.id}/marks`]: jsonResponse(200, { marks: [mark] }),
    [`GET /sessions/${session.id}/transcript`]: jsonResponse(200, {
      lines: [
        {
          words: [
            { index: 0, text: 'could' },
            { index: 1, text: 'have' },
          ],
        },
      ],
    }),
    [`GET ${listPath}`]: () =>
      jsonResponse(200, { cards: saved, remaining: 2 - saved.length, next_cursor: null }),
    [`POST ${path}`]: ({ body }) => {
      const added = { ...card, ...(body as object), id: `card-${saved.length + 1}` };
      saved.push(added);
      return jsonResponse(201, added);
    },
    'DELETE /cards/card-1': () => {
      saved.splice(0, 1);
      return new Response(null, { status: 204 });
    },
    [`POST ${path}/complete`]: new Response(null, { status: 204 }),
    [`POST /sessions/${session.id}/steps/card/skip`]: jsonResponse(
      200,
      sessionFixture({ done: 3, skipped: ['card'] }),
    ),
    ...extraRoutes,
  });
  const rendered = renderWithProviders(<CardScreen session={session} progress={<p>Progress</p>} />);
  return { ...rendered, ...routes };
}

test('blocksThirdCardWithoutDefinition and deletion frees its slot (AT-5, D14)', async () => {
  const { calls } = setup();
  await screen.findByRole('option', { name: /could have/ });
  fireEvent.change(screen.getByRole('combobox', { name: 'Marked phrase' }), {
    target: { value: mark.id },
  });
  expect(screen.getByRole('textbox', { name: 'Written form' })).toHaveValue('could have');
  expect(screen.queryByLabelText(/definition|translation/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('1 left');
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('0 left');
  expect(screen.getByRole('button', { name: 'Save card' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  expect(calls.filter((c) => c.method === 'POST' && c.path === path)).toHaveLength(2);
  fireEvent.click(screen.getAllByRole('button', { name: /Delete card/ })[0]);
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByRole('button', { name: 'Keep card' })).toHaveFocus();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Delete card' }));
  await screen.findByText('1 left');
  expect(screen.getByRole('link', { name: /Source at 00:11/ })).toHaveAttribute(
    'href',
    card.source_url,
  );
});

test('creates a card and completes the step', async () => {
  const { calls } = setup();
  await screen.findByRole('option', { name: /could have/ });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('1 left');
  fireEvent.click(screen.getByRole('button', { name: 'Finish Card' }));
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/cards/complete'))).toBe(true));
});

test('forms expose the 1 to 100 character limits', async () => {
  setup();
  await screen.findByRole('option', { name: /could have/ });
  for (const name of ['Written form', 'Heard form']) {
    const field = screen.getByRole('textbox', { name });
    expect(field).toBeRequired();
    expect(field).toHaveAttribute('maxlength', '100');
    expect(field).toHaveAttribute('minlength', '1');
  }
});

test('skip asks for confirmation and Escape returns focus', async () => {
  const { calls } = setup();
  const skip = await screen.findByRole('button', { name: 'Skip Card' });
  skip.focus();
  fireEvent.click(skip);
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  await waitFor(() => expect(skip).toHaveFocus());
  expect(calls.some((c) => c.path.includes('/skip'))).toBe(false);
  skip.focus();
  fireEvent.click(skip);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Skip Card' }));
  await waitFor(() => expect(calls.some((c) => c.path.includes('/skip'))).toBe(true));
});

test('a refused create keeps the forms and refreshes the count', async () => {
  setup();
  await screen.findByRole('option', { name: /could have/ });
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (init?.method === 'POST')
      return problem(409, 'card_limit_reached', 'This session already has two cards.');
    if (String(input).includes('/cards?'))
      return jsonResponse(200, {
        cards: [card, { ...card, id: 'card-2' }],
        remaining: 0,
        next_cursor: null,
      });
    return jsonResponse(200, {});
  });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('This session already has two cards.');
  expect(screen.getByRole('textbox', { name: 'Heard form' })).toHaveValue('kuduv');
  await screen.findByText('0 left');
});

test('save remains blocked while the authoritative count refreshes', async () => {
  setup([card]);
  await screen.findByRole('option', { name: /could have/ });
  await screen.findByText('1 left');
  const original = vi.mocked(fetch).getMockImplementation()!;
  let refreshing = false;
  let release!: (response: Response) => void;
  const pendingList = new Promise<Response>((resolve) => {
    release = resolve;
  });
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).includes('/cards?')) {
      refreshing = true;
      return pendingList;
    }
    return original(input, init);
  });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await waitFor(() => expect(refreshing).toBe(true));
  expect(screen.getByRole('button', { name: /Sav/ })).toHaveAttribute('aria-disabled', 'true');
  release(
    jsonResponse(200, {
      cards: [card, { ...card, id: 'card-2' }],
      remaining: 0,
      next_cursor: null,
    }),
  );
  await screen.findByText('0 left');
});

test('a failed count refresh after the second save still blocks a third card', async () => {
  const { calls } = setup([card]);
  await screen.findByRole('option', { name: /could have/ });
  await screen.findByText('1 left');
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).includes('/cards?')) return problem(503, 'unavailable', 'Cards unavailable');
    return original(input, init);
  });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('Cards unavailable');
  expect(screen.getByText('0 left')).toBeVisible();
  const save = screen.getByRole('button', { name: 'Save card' });
  expect(save).toHaveAttribute('aria-disabled', 'true');
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'another sound' },
  });
  fireEvent.click(save);
  expect(calls.filter((call) => call.method === 'POST' && call.path === path)).toHaveLength(1);
});

test('a replay after a lost response does not consume another cached slot', async () => {
  setup();
  await screen.findByRole('option', { name: /could have/ });
  const original = vi.mocked(fetch).getMockImplementation()!;
  const keys: string[] = [];
  let saved = card;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (init?.method === 'POST') {
      keys.push((init.headers as Record<string, string>)['Idempotency-Key']);
      if (keys.length === 1) {
        saved = await (await original(input, init)).json();
        throw new TypeError('Response lost');
      }
      return jsonResponse(201, saved);
    }
    if (keys.length === 2 && String(input).includes('/cards?'))
      return problem(503, 'unavailable', 'Cards unavailable');
    return original(input, init);
  });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('1 left');
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('Cards unavailable');
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
  expect(screen.getByText('1 left')).toBeVisible();
  expect(
    within(screen.getByRole('list', { name: 'Saved cards' })).getAllByRole('listitem'),
  ).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Save card' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
});

test('an uncertain save stays blocked until the failed list read recovers', async () => {
  const { calls } = setup([card]);
  await screen.findByRole('option', { name: /could have/ });
  await screen.findByText('1 left');
  const original = vi.mocked(fetch).getMockImplementation()!;
  let unavailable = true;
  let writes = 0;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (init?.method === 'POST') {
      writes++;
      throw new TypeError('Response lost');
    }
    if (unavailable && String(input).includes('/cards?'))
      return problem(503, 'unavailable', 'Cards unavailable');
    return original(input, init);
  });
  fireEvent.change(screen.getByRole('combobox'), { target: { value: mark.id } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Heard form' }), {
    target: { value: 'kuduv' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
  await screen.findByText('Cards unavailable');
  const save = screen.getByRole('button', { name: 'Save card' });
  expect(save).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(save);
  expect(writes).toBe(1);
  unavailable = false;
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await waitFor(() => expect(save).toHaveAttribute('aria-disabled', 'false'));
  expect(calls.filter((call) => call.path === listPath)).toHaveLength(2);
  expect(screen.getByRole('textbox', { name: 'Heard form' })).toHaveValue('kuduv');
});

test('empty marks and unavailable transcript still allow finishing', async () => {
  mockRoutes({
    [`GET /sessions/${session.id}/marks`]: jsonResponse(200, { marks: [] }),
    [`GET /sessions/${session.id}/transcript`]: problem(409, 'transcript_failed', 'Unavailable'),
    [`GET ${listPath}`]: jsonResponse(200, { cards: [], remaining: 2, next_cursor: null }),
  });
  renderWithProviders(<CardScreen session={session} progress={null} />);
  expect(await screen.findByText(/No marks in this session/)).toBeVisible();
  expect(await screen.findByText(/marked words are unavailable/)).toBeVisible();
  expect(screen.getByRole('button', { name: 'Finish Card' })).toHaveAttribute(
    'aria-disabled',
    'false',
  );
});

test('list and marks failures expose retry controls', async () => {
  const { calls } = mockRoutes({
    [`GET /sessions/${session.id}/marks`]: problem(429, 'rate_limited', 'Marks unavailable'),
    [`GET /sessions/${session.id}/transcript`]: jsonResponse(200, { lines: [] }),
    [`GET ${listPath}`]: problem(429, 'rate_limited', 'Cards unavailable'),
  });
  renderWithProviders(<CardScreen session={session} progress={null} />);
  await screen.findByText('Cards unavailable');
  await screen.findByText('Marks unavailable');
  for (const retry of screen.getAllByRole('button', { name: /Try again/ })) fireEvent.click(retry);
  await waitFor(() => expect(calls.filter((call) => call.path === listPath)).toHaveLength(2));
});

test('delete and finish refusals remain visible and deletion can be cancelled', async () => {
  setup([card]);
  await screen.findByRole('button', { name: /Delete card:/ });
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (init?.method === 'DELETE' || init?.method === 'POST')
      return problem(409, 'step_locked', 'Try the current step.');
    return original(input, init);
  });
  fireEvent.click(screen.getByRole('button', { name: /Delete card:/ }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete card' }));
  await within(screen.getByRole('dialog')).findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Keep card' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Finish Card' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Try the current step.');
});

test('plays saved card audio and reports playback failure accessibly', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  setup([{ ...card, audio_status: 'ready' }]);
  const button = await screen.findByRole('button', { name: 'Play audio: could have' });
  fireEvent.click(button);
  await waitFor(() => expect(play).toHaveBeenCalled());
  const audio = document.querySelector('audio')!;
  expect(audio).toHaveAttribute('src', '/api/v1/cards/card-1/audio');
  fireEvent.error(audio);
  expect(await screen.findByRole('alert')).toHaveTextContent(/audio could not play/i);
});

test('pending audio has a focusable reason and never starts playback', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  setup([{ ...card, audio_status: 'pending' }]);
  const button = await screen.findByRole('button', { name: 'Play audio: could have' });
  expect(button).toHaveAttribute('aria-disabled', 'true');
  expect(button).toHaveAccessibleDescription(/preparing/i);
  fireEvent.click(button);
  expect(play).not.toHaveBeenCalled();
});

test('failed audio offers a retry and reports a refused retry', async () => {
  setup([{ ...card, audio_status: 'failed' }]);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry audio: could have' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
});

test('removing the card screen stops its playing audio', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const { unmount } = setup([{ ...card, audio_status: 'ready' }]);
  fireEvent.click(await screen.findByRole('button', { name: 'Play audio: could have' }));
  unmount();
  expect(pause).toHaveBeenCalled();
});

test('a lost retry response reloads the authoritative pending state', async () => {
  let status = 'failed';
  setup([{ ...card, audio_status: status }], {
    [`GET ${listPath}`]: () =>
      jsonResponse(200, {
        cards: [{ ...card, audio_status: status }],
        remaining: 1,
        next_cursor: null,
      }),
    'POST /cards/card-1/audio/retry': () => {
      status = 'pending';
      return problem(503, 'unavailable', 'Response lost');
    },
  });
  fireEvent.click(await screen.findByRole('button', { name: 'Retry audio: could have' }));
  expect(await screen.findByText('Preparing audio…')).toBeVisible();
});

test('pending audio polls and announces when it becomes playable without an event', async () => {
  let reads = 0;
  setup([{ ...card, audio_status: 'pending' }], {
    [`GET ${listPath}`]: () =>
      jsonResponse(200, {
        cards: [{ ...card, audio_status: ++reads > 1 ? 'ready' : 'pending' }],
        remaining: 1,
        next_cursor: null,
      }),
  });
  expect(await screen.findByText('Preparing audio…')).toBeVisible();
  expect(await screen.findByText('Audio ready: could have', {}, { timeout: 5000 })).toHaveAttribute(
    'role',
    'status',
  );
  expect(screen.getByRole('button', { name: 'Play audio: could have' })).toHaveAttribute(
    'aria-disabled',
    'false',
  );
});
