import { ApiError } from '../../api/client';
import { MarkSync, type MarkTransport, type SavedMark } from './markSync';

const KEY = 'listenup:marks:s1';

function saved(id: string, word_from: number, note: string | null = null): SavedMark {
  return {
    id,
    session_id: 's1',
    word_from,
    word_to: word_from,
    at_ms: 1000 * word_from,
    note,
    source: 'manual',
    status: 'confirmed',
    created_at: '2026-10-19T10:00:00Z',
  };
}

function memoryStorage() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}

function refusal(status: number, code: string, extra: Record<string, unknown> = {}) {
  return new ApiError({ type: '', title: '', status, detail: code, code, ...extra });
}

function fakeServer(initial: SavedMark[] = []) {
  const marks = new Map(initial.map((mark) => [mark.id, mark]));
  const transport = {
    create: vi.fn(
      async (mark: { id: string; word_from: number; word_to: number; note: string | null }) => {
        const stored = { ...saved(mark.id, mark.word_from, mark.note), word_to: mark.word_to };
        marks.set(mark.id, stored);
        return stored;
      },
    ),
    setNote: vi.fn(async (id: string, note: string | null) => {
      const mark = marks.get(id);
      if (!mark) throw refusal(404, 'mark_not_found');
      const changed = { ...mark, note };
      marks.set(id, changed);
      return changed;
    }),
    remove: vi.fn(async (id: string) => {
      if (!marks.delete(id)) throw refusal(404, 'mark_not_found');
    }),
    list: vi.fn(async () => [...marks.values()]),
  } satisfies MarkTransport;
  return { marks, transport };
}

let online = true;
function make(
  transport: MarkTransport,
  storage = memoryStorage(),
  marks: SavedMark[] = [],
  backoffMs = (n: number) => 1000 * n,
) {
  const sync = new MarkSync({
    storageKey: KEY,
    marks,
    transport,
    storage,
    backoffMs,
    isOnline: () => online,
    offlinePollMs: 60_000,
  });
  sync.start();
  return sync;
}

beforeEach(() => {
  vi.useFakeTimers();
  online = true;
});
afterEach(() => {
  vi.useRealTimers();
});

/** The tab closes: its pending debounce never fires. */
const closeTab = () => vi.clearAllTimers();

const ids = (sync: MarkSync) => sync.getSnapshot().marks.map((mark) => mark.id);

test('a_new_mark_shows_at_once_is_kept_on_the_device_and_saved_after_the_debounce', async () => {
  const { transport, marks } = fakeServer();
  const storage = memoryStorage();
  const sync = make(transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 3, at_ms: 2000, note: null });
  const shown = sync.getSnapshot();
  expect(shown.marks).toMatchObject([{ id: 'm1', word_from: 2, word_to: 3, saved: false }]);
  expect(shown.status.kind).toBe('pending');
  expect(JSON.parse(storage.items.get(KEY)!)).toMatchObject({ ops: [{ op: 'create' }] });
  await vi.advanceTimersByTimeAsync(1999);
  expect(transport.create).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(transport.create).toHaveBeenCalledWith({ id: 'm1', word_from: 2, word_to: 3, note: null });
  expect(marks.has('m1')).toBe(true);
  expect(sync.getSnapshot().marks[0]).toMatchObject({ id: 'm1', saved: true });
  expect(sync.getSnapshot().status.kind).toBe('saved');
  expect(storage.items.has(KEY)).toBe(false);
});

test('marks_are_shown_in_audio_order', () => {
  const { transport } = fakeServer();
  const sync = make(transport, memoryStorage(), [saved('b', 5)]);
  sync.add({ id: 'a', word_from: 1, word_to: 1, at_ms: 1000, note: null });
  expect(ids(sync)).toEqual(['a', 'b']);
});

test('unsaved_marks_survive_a_reload_and_are_sent_once_the_page_is_back', async () => {
  const { transport } = fakeServer([saved('old', 0)]);
  const storage = memoryStorage();
  const first = make(transport, storage, [saved('old', 0)]);
  first.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: 'linking' });
  first.setNote('old', 'changed');
  // The tab closes before the debounce: nothing was sent, both edits are on the device.
  closeTab();
  expect(transport.create).not.toHaveBeenCalled();
  const again = make(transport, storage, [saved('old', 0)]);
  expect(again.getSnapshot().restored).toBe(true);
  expect(again.getSnapshot().marks).toMatchObject([
    { id: 'old', note: 'changed', saved: false },
    { id: 'm1', note: 'linking', saved: false },
  ]);
  await vi.runOnlyPendingTimersAsync();
  await vi.runOnlyPendingTimersAsync();
  expect(transport.create).toHaveBeenCalledTimes(1);
  expect(transport.setNote).toHaveBeenCalledWith('old', 'changed');
  expect(again.getSnapshot().status.kind).toBe('saved');
});

test('a_restored_copy_already_on_the_server_is_not_sent_again', async () => {
  const { transport } = fakeServer();
  const storage = memoryStorage();
  make(transport, storage).add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  closeTab();
  const again = make(transport, storage, [saved('m1', 2)]);
  expect(again.getSnapshot().restored).toBe(false);
  expect(again.getSnapshot().marks).toMatchObject([{ id: 'm1', saved: true }]);
  expect(storage.items.has(KEY)).toBe(false);
});

test('a_restored_removal_or_note_for_a_mark_gone_from_the_server_is_dropped', () => {
  const { transport } = fakeServer();
  const storage = memoryStorage();
  const first = make(transport, storage, [saved('a', 1), saved('b', 2)]);
  first.remove('a');
  first.setNote('b', 'x');
  closeTab();
  const again = make(transport, storage, []);
  expect(again.getSnapshot().marks).toEqual([]);
  expect(again.getSnapshot().status.kind).toBe('saved');
});

test('a_restored_removal_hides_the_mark_until_it_is_sent', async () => {
  const { transport, marks } = fakeServer([saved('a', 1)]);
  const storage = memoryStorage();
  make(transport, storage, [saved('a', 1)]).remove('a');
  closeTab();
  const again = make(transport, storage, [saved('a', 1)]);
  expect(again.getSnapshot().marks).toEqual([]);
  await vi.runOnlyPendingTimersAsync();
  expect(marks.has('a')).toBe(false);
});

test('a_lost_connection_keeps_the_mark_here_and_sends_it_when_the_connection_returns', async () => {
  const { transport } = fakeServer();
  const create = transport.create;
  transport.create = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'));
  transport.create.mockImplementation(create);
  const storage = memoryStorage();
  const sync = make(transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('offline');
  expect(storage.items.has(KEY)).toBe(true);
  window.dispatchEvent(new Event('online'));
  await vi.advanceTimersByTimeAsync(0);
  // The resend names the same mark, so a create that did reach the server is not doubled.
  expect(transport.create.mock.calls.map(([mark]) => mark.id)).toEqual(['m1', 'm1']);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('while_offline_nothing_is_sent_and_the_poll_tries_again', async () => {
  const { transport } = fakeServer();
  online = false;
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('offline');
  expect(transport.create).not.toHaveBeenCalled();
  online = true;
  await vi.advanceTimersByTimeAsync(60_000);
  expect(transport.create).toHaveBeenCalledTimes(1);
});

test('a_busy_server_is_tried_again_after_a_pause', async () => {
  const { transport } = fakeServer();
  const create = transport.create;
  transport.create = vi.fn().mockRejectedValueOnce(refusal(503, 'service_unavailable'));
  transport.create.mockImplementation(create);
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('retrying');
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport.create).toHaveBeenCalledTimes(2);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('a_refused_mark_is_taken_back_and_the_refusal_is_shown', async () => {
  const { transport } = fakeServer();
  transport.create = vi.fn().mockRejectedValue(refusal(422, 'mark_too_long'));
  const storage = memoryStorage();
  const sync = make(transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 30, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toEqual([]);
  expect(sync.getSnapshot().status).toMatchObject({ kind: 'failed' });
  expect(storage.items.has(KEY)).toBe(false);
});

test('words_marked_in_another_tab_show_that_tabs_mark', async () => {
  const { transport, marks } = fakeServer();
  marks.set('theirs', { ...saved('theirs', 2), note: 'from the other tab' });
  transport.create = vi.fn().mockRejectedValue(refusal(409, 'mark_exists', { mark_id: 'theirs' }));
  const sync = make(transport);
  sync.add({ id: 'mine', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.list).toHaveBeenCalled();
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'theirs', note: 'from the other tab', saved: true },
  ]);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('removing_an_unsent_mark_sends_nothing', async () => {
  const { transport } = fakeServer();
  const storage = memoryStorage();
  const sync = make(transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  sync.setNote('m1', 'weak form');
  sync.remove('m1');
  await vi.advanceTimersByTimeAsync(5000);
  expect(transport.create).not.toHaveBeenCalled();
  expect(transport.remove).not.toHaveBeenCalled();
  expect(sync.getSnapshot().marks).toEqual([]);
  expect(storage.items.has(KEY)).toBe(false);
});

test('a_note_written_before_the_first_save_goes_with_the_create', async () => {
  const { transport } = fakeServer();
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  sync.setNote('m1', 'weak form');
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.create).toHaveBeenCalledWith(expect.objectContaining({ note: 'weak form' }));
  expect(transport.setNote).not.toHaveBeenCalled();
});

test('edits_made_while_a_save_is_on_its_way_follow_it', async () => {
  const { transport } = fakeServer();
  const create = transport.create;
  let release = () => {};
  transport.create = vi.fn(
    (mark) => new Promise((resolve) => (release = () => resolve(create(mark)))),
  );
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  sync.add({ id: 'm2', word_from: 3, word_to: 3, at_ms: 3000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('saving');
  sync.setNote('m1', 'late note');
  release();
  await vi.advanceTimersByTimeAsync(0);
  release();
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.setNote).toHaveBeenCalledWith('m1', 'late note');
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'm1', note: 'late note', saved: true },
    { id: 'm2', saved: true },
  ]);
});

test('a_mark_removed_while_its_create_is_on_its_way_is_removed_after_it', async () => {
  const { transport, marks } = fakeServer();
  const create = transport.create;
  let release = () => {};
  transport.create = vi.fn(
    (mark) => new Promise((resolve) => (release = () => resolve(create(mark)))),
  );
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  sync.remove('m1');
  expect(sync.getSnapshot().marks).toEqual([]);
  release();
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.remove).toHaveBeenCalledWith('m1');
  expect(marks.size).toBe(0);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('changing_and_removing_saved_marks', async () => {
  const { transport, marks } = fakeServer([saved('a', 1), saved('b', 2)]);
  const sync = make(transport, memoryStorage(), [saved('a', 1), saved('b', 2)]);
  sync.setNote('a', 'linking');
  sync.setNote('a', 'linking'); // the same note again changes nothing
  sync.remove('b');
  expect(ids(sync)).toEqual(['a']);
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.setNote).toHaveBeenCalledTimes(1);
  expect(marks.get('a')?.note).toBe('linking');
  expect(marks.has('b')).toBe(false);
});

test('a_mark_already_gone_from_the_server_counts_as_removed', async () => {
  const { transport } = fakeServer();
  const sync = make(transport, memoryStorage(), [saved('a', 1), saved('b', 2)]);
  sync.setNote('a', 'x');
  sync.remove('b');
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toEqual([]);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('leaving_the_page_sends_what_is_left_once', async () => {
  const { transport } = fakeServer();
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  sync.stop();
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.create).toHaveBeenCalledTimes(1);
  sync.stop(); // a second stop does nothing
});

test('flush_sends_without_waiting_for_the_debounce', async () => {
  const { transport } = fakeServer();
  const sync = make(transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  sync.flush();
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.create).toHaveBeenCalledTimes(1);
});

test('blocked_or_damaged_device_storage_never_breaks_marking', async () => {
  const { transport } = fakeServer();
  const broken = {
    getItem: () => '{not json',
    setItem: () => {
      throw new Error('quota');
    },
    removeItem: () => {
      throw new Error('blocked');
    },
  };
  const sync = make(transport, broken as never);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'm1', saved: true }]);
});

test('a_note_change_that_meets_a_lost_connection_waits_for_it', async () => {
  const { transport } = fakeServer([saved('a', 1)]);
  const setNote = transport.setNote;
  transport.setNote = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'));
  transport.setNote.mockImplementation(setNote);
  const sync = make(transport, memoryStorage(), [saved('a', 1)]);
  sync.setNote('a', 'linking');
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('offline');
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'a', note: 'linking', saved: false }]);
  window.dispatchEvent(new Event('online'));
  await vi.advanceTimersByTimeAsync(0);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'a', note: 'linking', saved: true }]);
});

test('a_failed_reload_after_words_marked_elsewhere_is_reported', async () => {
  const { transport } = fakeServer();
  transport.create = vi.fn().mockRejectedValue(refusal(409, 'mark_exists', { mark_id: 'x' }));
  transport.list = vi.fn().mockRejectedValue(refusal(403, 'forbidden'));
  const sync = make(transport);
  sync.add({ id: 'mine', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toEqual([]);
  expect(sync.getSnapshot().status).toMatchObject({ kind: 'failed' });
});
