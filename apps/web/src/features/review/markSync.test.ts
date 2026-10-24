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
    // Like the API: a resend of a stored id answers with the stored mark, note and all,
    // and changes nothing (ON CONFLICT DO NOTHING, ADR 0047).
    create: vi.fn(
      async (mark: { id: string; word_from: number; word_to: number; note: string | null }) => {
        const existing = marks.get(mark.id);
        if (existing) return existing;
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
    confirm: vi.fn(async (id: string) => {
      const mark = marks.get(id);
      if (!mark) throw refusal(404, 'mark_not_found');
      const changed = { ...mark, status: 'confirmed' as const };
      marks.set(id, changed);
      return changed;
    }),
    // Like the Dictation route (ADR 0055): a stored id or words already marked give back
    // the mark they have; otherwise the words come back from Dictation, to confirm.
    restore: vi.fn(async (mark: { id: string; word_from: number; word_to: number }) => {
      const existing =
        marks.get(mark.id) ??
        [...marks.values()].find(
          (other) => other.word_from === mark.word_from && other.word_to === mark.word_to,
        );
      if (existing) return existing;
      const stored = {
        ...saved(mark.id, mark.word_from),
        word_to: mark.word_to,
        source: 'dictation' as const,
        status: 'suggested' as const,
      };
      marks.set(mark.id, stored);
      return stored;
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

// -- a refusal that is not a refused create (NFR-REL-1: a saved mark is never lost) --------

test('a_refused_note_change_puts_back_the_saved_note_and_keeps_the_mark', async () => {
  const { transport } = fakeServer([saved('m1', 1, 'old')]);
  transport.setNote = vi.fn().mockRejectedValue(refusal(422, 'note_too_long'));
  const storage = memoryStorage();
  const sync = make(transport, storage, [saved('m1', 1, 'old')]);
  sync.setNote('m1', 'new');
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'm1', note: 'old', saved: true }]);
  expect(sync.getSnapshot().status).toMatchObject({ kind: 'failed' });
  expect(storage.items.has(KEY)).toBe(false);
});

test('a_refused_removal_keeps_the_mark_on_screen', async () => {
  const { transport } = fakeServer([saved('m1', 1)]);
  transport.remove = vi.fn().mockRejectedValue(refusal(409, 'step_locked'));
  const sync = make(transport, memoryStorage(), [saved('m1', 1)]);
  sync.remove('m1');
  expect(ids(sync)).toEqual([]);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'm1', saved: true }]);
  expect(sync.getSnapshot().status).toMatchObject({ kind: 'failed' });
});

test('a_signed_out_learner_keeps_every_change_on_the_device_and_nothing_is_retried_blindly', async () => {
  const { transport } = fakeServer([saved('m1', 1)]);
  transport.setNote = vi.fn().mockRejectedValue(refusal(401, 'not_signed_in'));
  const storage = memoryStorage();
  const sync = make(transport, storage, [saved('m1', 1)]);
  sync.setNote('m1', 'weak form');
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'm1', note: 'weak form', saved: false }]);
  expect(sync.getSnapshot().status).toMatchObject({ kind: 'failed' });
  expect(JSON.parse(storage.items.get(KEY)!)).toMatchObject({ ops: [{ op: 'update' }] });
  await vi.advanceTimersByTimeAsync(60_000);
  expect(transport.setNote).toHaveBeenCalledTimes(1);
  // The next change is a fresh attempt, and the kept note goes with it.
  transport.setNote = vi.fn(async (id: string, note: string | null) => ({ ...saved(id, 1), note }));
  sync.setNote('m1', 'weak form, linking');
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.setNote).toHaveBeenCalledWith('m1', 'weak form, linking');
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

// -- a create whose answer was lost may be on the server ------------------------------------

/** The first create reaches the server but its answer never comes back. */
function lostAnswer(server: ReturnType<typeof fakeServer>) {
  const { transport } = server;
  const create = transport.create.getMockImplementation()!;
  transport.create.mockImplementationOnce(async (mark) => {
    await create(mark);
    throw new TypeError('Failed to fetch');
  });
}

test('removing_a_mark_whose_create_answer_was_lost_still_removes_it_from_the_server', async () => {
  const server = fakeServer();
  lostAnswer(server);
  const sync = make(server.transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().status.kind).toBe('offline');
  expect(server.marks.has('m1')).toBe(true);
  sync.remove('m1');
  expect(ids(sync)).toEqual([]);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(server.transport.remove).toHaveBeenCalledWith('m1');
  expect(server.marks.has('m1')).toBe(false);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('that_removal_survives_a_reload_even_when_the_page_loaded_before_the_create_landed', async () => {
  const server = fakeServer();
  lostAnswer(server);
  const storage = memoryStorage();
  const sync = make(server.transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  sync.remove('m1');
  expect(JSON.parse(storage.items.get(KEY)!)).toMatchObject({ ops: [{ op: 'delete' }] });
  closeTab();
  const again = make(server.transport, storage, []); // the list that loaded the page lacks m1
  expect(again.getSnapshot().marks).toEqual([]);
  await vi.runOnlyPendingTimersAsync();
  expect(server.marks.has('m1')).toBe(false);
});

test('a_note_written_after_a_lost_create_answer_still_reaches_the_server', async () => {
  const server = fakeServer();
  lostAnswer(server);
  const sync = make(server.transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(server.marks.get('m1')).toMatchObject({ note: null });
  sync.setNote('m1', 'sounds like one word');
  await vi.advanceTimersByTimeAsync(60_000);
  // The resent create answers with the stored mark and its old note: the note follows.
  expect(server.transport.setNote).toHaveBeenCalledWith('m1', 'sounds like one word');
  expect(server.marks.get('m1')).toMatchObject({ note: 'sounds like one word' });
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'm1', note: 'sounds like one word', saved: true },
  ]);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('that_note_survives_a_reload_before_the_resend', async () => {
  const server = fakeServer();
  lostAnswer(server);
  const storage = memoryStorage();
  const sync = make(server.transport, storage);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  sync.setNote('m1', 'linking');
  closeTab();
  const again = make(server.transport, storage, []); // the list that loaded the page lacks m1
  await vi.runOnlyPendingTimersAsync();
  await vi.runOnlyPendingTimersAsync();
  expect(server.marks.get('m1')).toMatchObject({ note: 'linking' });
  expect(again.getSnapshot().marks).toMatchObject([{ id: 'm1', note: 'linking', saved: true }]);
});

// -- reloading the list ----------------------------------------------------------------------

test('a_reload_takes_the_other_tabs_notes_and_removals_but_keeps_unsent_changes', async () => {
  const { transport, marks } = fakeServer();
  marks.set('a', saved('a', 0, 'from the other tab'));
  marks.set('theirs', saved('theirs', 3));
  transport.create = vi.fn().mockRejectedValue(refusal(409, 'mark_exists', { mark_id: 'theirs' }));
  const sync = make(transport, memoryStorage(), [saved('a', 0, 'old'), saved('gone', 5)]);
  sync.add({ id: 'mine', word_from: 3, word_to: 3, at_ms: 3000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'a', note: 'from the other tab' },
    { id: 'theirs' },
  ]);
});

test('a_refused_removal_of_a_mark_never_confirmed_puts_it_back_and_sends_it_again', async () => {
  const server = fakeServer();
  lostAnswer(server);
  server.transport.remove = vi.fn().mockRejectedValue(refusal(403, 'forbidden'));
  const sync = make(server.transport);
  sync.add({ id: 'm1', word_from: 2, word_to: 2, at_ms: 2000, note: null });
  await vi.advanceTimersByTimeAsync(2000);
  sync.remove('m1');
  await vi.advanceTimersByTimeAsync(62_000);
  expect(ids(sync)).toEqual(['m1']);
  expect(server.transport.create).toHaveBeenCalledTimes(2);
  expect(sync.getSnapshot().marks[0]).toMatchObject({ saved: true });
});

test('saved_marks_made_elsewhere_on_the_page_are_taken_without_sending_or_overwriting', async () => {
  // The Dictation result inside Transcript adds marks through its own route (#55).
  const { transport } = fakeServer([saved('m1', 0)]);
  const storage = memoryStorage();
  const sync = make(transport, storage, [saved('m1', 0)]);
  sync.setNote('m1', 'local note');
  sync.takeSaved([saved('m1', 0, 'older note'), saved('d1', 2, 'from another tab')]);
  expect(sync.getSnapshot().marks.map((mark) => [mark.id, mark.note, mark.saved])).toEqual([
    ['m1', 'local note', false],
    ['d1', 'from another tab', true],
  ]);
  expect(storage.items.get(KEY) ?? '').not.toContain('d1');
  expect(transport.create).not.toHaveBeenCalled();
  sync.stop();
});

test('undo_during_an_in_flight_delete_recreates_the_mark_with_its_note', async () => {
  const mark = saved('m1', 2, 'linking');
  const server = fakeServer([mark]);
  let finishDelete!: () => void;
  server.transport.remove = vi.fn(async (id: string) => {
    await new Promise<void>((resolve) => {
      finishDelete = resolve;
    });
    server.marks.delete(id);
  });
  const sync = make(server.transport, memoryStorage(), [mark]);
  sync.remove(mark.id);
  await vi.advanceTimersByTimeAsync(2000);
  sync.add(mark); // Undo while DELETE is still on its way.
  finishDelete();
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: 'm1', note: 'linking', saved: true }]);
  expect(server.marks.get('m1')).toMatchObject({ note: 'linking' });
});

test('remove_undo_remove_before_saving_still_deletes_the_saved_mark', async () => {
  const mark = saved('m1', 2, 'linking');
  const server = fakeServer([mark]);
  const sync = make(server.transport, memoryStorage(), [mark]);
  sync.remove(mark.id);
  sync.add(mark); // Undo before the original DELETE was sent.
  sync.remove(mark.id);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toEqual([]);
  expect(server.marks.has(mark.id)).toBe(false);
});

test('undo_cancels_an_unsent_saved_deletion_without_a_refusable_create', async () => {
  const mark = saved('m1', 2, 'linking');
  const server = fakeServer([mark]);
  server.transport.create.mockRejectedValue(refusal(403, 'consent_required'));
  const sync = make(server.transport, memoryStorage(), [mark]);
  sync.remove(mark.id);
  sync.add(mark);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: mark.id, note: 'linking', saved: true }]);
  expect(sync.getSnapshot().hasPendingChanges).toBe(false);
  expect(server.transport.create).not.toHaveBeenCalled();
  expect(server.transport.remove).not.toHaveBeenCalled();
  expect(server.marks.get(mark.id)).toEqual(mark);
});

test('a_refused_note_after_undo_restores_the_known_server_mark_and_note', async () => {
  const mark = saved('m1', 2, 'saved note');
  const server = fakeServer([mark]);
  server.transport.create.mockRejectedValue(refusal(403, 'forbidden'));
  server.transport.setNote.mockRejectedValue(refusal(403, 'forbidden'));
  const sync = make(server.transport, memoryStorage(), [mark]);
  sync.setNote(mark.id, 'unsaved note');
  const removed = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  sync.add(removed);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: mark.id, note: 'saved note', saved: true },
  ]);
  expect(sync.getSnapshot().hasPendingChanges).toBe(false);
  expect(server.marks.get(mark.id)).toEqual(mark);
});

test.each(['undo', 'note', 'remove'])(
  'undo_of_an_in_flight_refused_delete_preserves_the_saved_mark_after_%s',
  async (next) => {
    const mark = saved('m1', 2, 'linking');
    const server = fakeServer([mark]);
    let refuseDelete!: (error: unknown) => void;
    server.transport.remove = vi.fn(
      () =>
        new Promise<void>((_resolve, reject) => {
          refuseDelete = reject;
        }),
    );
    server.transport.create.mockRejectedValue(refusal(403, 'forbidden'));
    const sync = make(server.transport, memoryStorage(), [mark]);
    sync.remove(mark.id);
    await vi.advanceTimersByTimeAsync(2000);
    sync.add(mark);
    if (next === 'note') {
      server.transport.setNote.mockRejectedValue(refusal(403, 'forbidden'));
      sync.setNote(mark.id, 'unsaved note');
    } else if (next === 'remove') sync.remove(mark.id);
    refuseDelete(refusal(403, 'forbidden'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(sync.getSnapshot().marks).toMatchObject([{ id: mark.id, note: 'linking', saved: true }]);
    expect(sync.getSnapshot().hasPendingChanges).toBe(false);
    expect(server.transport.create).not.toHaveBeenCalled();
    expect(server.marks.get(mark.id)).toEqual(mark);
  },
);

test('undo_after_a_lost_delete_response_recreates_the_persisted_mark_and_note', async () => {
  const mark = saved('m1', 2, 'linking');
  const server = fakeServer([mark]);
  server.transport.remove = vi.fn(async (id: string) => {
    server.marks.delete(id);
    throw new TypeError('Lost DELETE response');
  });
  const sync = make(server.transport, memoryStorage(), [mark]);
  sync.remove(mark.id);
  await vi.advanceTimersByTimeAsync(2000);
  expect(server.marks.has(mark.id)).toBe(false);
  sync.add(mark);
  sync.flush();
  await vi.advanceTimersByTimeAsync(0);
  expect(server.marks.get(mark.id)).toEqual(mark);
  expect(sync.getSnapshot().marks).toMatchObject([{ id: mark.id, note: 'linking', saved: true }]);
});

// -- Dictation marks: confirm or remove (#59, FR-TR-3) ------------------------------------

function suggested(id: string, word_from: number): SavedMark {
  return { ...saved(id, word_from), source: 'dictation', status: 'suggested' };
}

test('dictation_marks_keep_their_source_and_status_on_screen', () => {
  const { transport } = fakeServer();
  const sync = make(transport, memoryStorage(), [suggested('d1', 1)]);
  sync.takeSaved([{ ...suggested('d2', 3) }]);
  sync.add({ id: 'm1', word_from: 5, word_to: 5, at_ms: 5000, note: null });
  expect(
    sync.getSnapshot().marks.map(({ id, source, status }) => ({ id, source, status })),
  ).toEqual([
    { id: 'd1', source: 'dictation', status: 'suggested' },
    { id: 'd2', source: 'dictation', status: 'suggested' },
    { id: 'm1', source: 'manual', status: 'confirmed' },
  ]);
});

test('confirming_a_dictation_mark_shows_at_once_and_is_saved_within_a_second', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const storage = memoryStorage();
  const sync = make(transport, storage, [suggested('d1', 1)]);
  sync.confirm('d1');
  expect(sync.getSnapshot().marks[0]).toMatchObject({ status: 'confirmed', saved: false });
  expect(JSON.parse(storage.items.get(KEY)!)).toMatchObject({
    ops: [{ op: 'update', mark: { id: 'd1', status: 'confirmed' } }],
  });
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport.confirm).toHaveBeenCalledWith('d1');
  expect(transport.setNote).not.toHaveBeenCalled();
  expect(marks.get('d1')!.status).toBe('confirmed');
  expect(sync.getSnapshot().marks[0]).toMatchObject({ status: 'confirmed', saved: true });
  expect(storage.items.has(KEY)).toBe(false);
});

test('removing_a_mark_is_saved_within_a_second', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const sync = make(transport, memoryStorage(), [suggested('d1', 1)]);
  sync.remove('d1');
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport.remove).toHaveBeenCalledWith('d1');
  expect(marks.has('d1')).toBe(false);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('confirming_a_mark_already_confirmed_sends_nothing', async () => {
  const { transport } = fakeServer([saved('m1', 1)]);
  const sync = make(transport, memoryStorage(), [saved('m1', 1)]);
  sync.confirm('m1');
  sync.confirm('unknown');
  await vi.advanceTimersByTimeAsync(5000);
  expect(transport.confirm).not.toHaveBeenCalled();
  expect(sync.getSnapshot().hasPendingChanges).toBe(false);
});

test('an_unsent_confirmation_survives_a_reload_and_is_sent_then', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const storage = memoryStorage();
  online = false;
  make(transport, storage, [suggested('d1', 1)]).confirm('d1');
  closeTab();
  online = true;
  const again = make(transport, storage, [suggested('d1', 1)]);
  expect(again.getSnapshot()).toMatchObject({
    restored: true,
    marks: [{ id: 'd1', status: 'confirmed', saved: false }],
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.confirm).toHaveBeenCalledWith('d1');
  expect(marks.get('d1')!.status).toBe('confirmed');
});

test('a_confirmation_and_a_note_on_one_mark_both_reach_the_server', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const sync = make(transport, memoryStorage(), [suggested('d1', 1)]);
  sync.setNote('d1', 'linking');
  sync.confirm('d1');
  await vi.advanceTimersByTimeAsync(1000);
  expect(marks.get('d1')).toMatchObject({ note: 'linking', status: 'confirmed' });
  expect(sync.getSnapshot().marks[0]).toMatchObject({
    note: 'linking',
    status: 'confirmed',
    saved: true,
  });
});

test('a_refused_confirmation_shows_the_mark_as_the_server_holds_it', async () => {
  const { transport } = fakeServer([suggested('d1', 1)]);
  transport.confirm.mockRejectedValueOnce(refusal(409, 'step_locked'));
  const sync = make(transport, memoryStorage(), [suggested('d1', 1)]);
  sync.confirm('d1');
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.getSnapshot().marks[0]).toMatchObject({ status: 'suggested', saved: true });
  expect(sync.getSnapshot().status.kind).toBe('failed');
});

test('a_mark_removed_elsewhere_drops_its_confirmation', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const sync = make(transport, memoryStorage(), [suggested('d1', 1)]);
  marks.delete('d1');
  sync.confirm('d1');
  await vi.advanceTimersByTimeAsync(1000);
  expect(ids(sync)).toEqual([]);
  expect(sync.getSnapshot().status.kind).toBe('saved');
});

test('an_unsent_note_on_a_dictation_mark_survives_a_reload_and_leaves_it_to_confirm', async () => {
  const { transport, marks } = fakeServer([suggested('d1', 1)]);
  const storage = memoryStorage();
  online = false;
  make(transport, storage, [suggested('d1', 1)]).setNote('d1', 'weak form');
  closeTab();
  online = true;
  const again = make(transport, storage, [suggested('d1', 1)]);
  expect(again.getSnapshot().marks[0]).toMatchObject({ note: 'weak form', status: 'suggested' });
  await vi.advanceTimersByTimeAsync(0);
  expect(transport.confirm).not.toHaveBeenCalled();
  expect(marks.get('d1')).toMatchObject({ note: 'weak form', status: 'suggested' });
});

test('undo_of_a_refused_inflight_dictation_deletion_restores_the_saved_source_and_status', async () => {
  const initial = {
    ...saved('d1', 0, 'linking'),
    source: 'dictation',
    status: 'suggested',
  } as const;
  const { transport } = fakeServer([initial]);
  let reject!: (error: unknown) => void;
  transport.remove.mockImplementationOnce(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
  );
  const sync = make(transport, memoryStorage(), [initial]);
  const mark = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  sync.flush();
  sync.add(mark);
  reject(refusal(403, 'forbidden'));
  await vi.advanceTimersByTimeAsync(0);
  expect(sync.getSnapshot().marks[0]).toMatchObject({
    source: 'dictation',
    status: 'suggested',
    note: 'linking',
    saved: true,
  });
});

test('a_reload_after_undo_of_an_unlanded_dictation_removal_leaves_the_mark_to_confirm', async () => {
  // Undo during the DELETE, then the tab reloads before the DELETE lands: the server
  // still holds the suggestion, and the kept op must not confirm it for the learner.
  const initial = { ...suggested('d1', 0), note: 'linking' };
  const { transport, marks } = fakeServer([initial]);
  transport.remove.mockImplementationOnce(() => new Promise<void>(() => {}));
  const storage = memoryStorage();
  const sync = make(transport, storage, [initial]);
  const mark = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  sync.flush();
  sync.add(mark);
  sync.setNote(mark.id, 'linking, then a weak form');
  closeTab();
  const reloaded = make(transport, storage, [...marks.values()]);
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.confirm).not.toHaveBeenCalled();
  expect(marks.get('d1')).toMatchObject({
    source: 'dictation',
    status: 'suggested',
    note: 'linking, then a weak form',
  });
  expect(reloaded.getSnapshot().marks).toMatchObject([
    { source: 'dictation', status: 'suggested', note: 'linking, then a weak form', saved: true },
  ]);
});

// -- Undo of a removed Dictation mark keeps its source (#59, ADR 0057) ---------------------

async function removedAndSaved(initial: SavedMark) {
  const server = fakeServer([initial]);
  const storage = memoryStorage();
  const sync = make(server.transport, storage, [initial]);
  const mark = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  await vi.advanceTimersByTimeAsync(0);
  expect(server.marks.has(mark.id)).toBe(false);
  return { ...server, storage, sync, mark };
}

test('undo_of_a_saved_dictation_removal_brings_the_mark_back_from_dictation_to_confirm', async () => {
  const { transport, marks, sync, mark } = await removedAndSaved({
    ...suggested('d1', 2),
    note: 'linking',
  });
  sync.undoRemove(mark);
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'd1', source: 'dictation', status: 'suggested', note: 'linking', saved: false },
  ]);
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.restore).toHaveBeenCalledWith({ id: 'd1', word_from: 2, word_to: 2 });
  expect(transport.create).not.toHaveBeenCalled();
  expect(transport.confirm).not.toHaveBeenCalled();
  expect(marks.get('d1')).toMatchObject({
    source: 'dictation',
    status: 'suggested',
    note: 'linking',
  });
  expect(sync.getSnapshot().marks).toMatchObject([
    { source: 'dictation', status: 'suggested', note: 'linking', saved: true },
  ]);
});

test('undo_of_a_saved_removal_of_a_confirmed_dictation_mark_keeps_it_confirmed', async () => {
  const { marks, sync, mark } = await removedAndSaved({
    ...suggested('d1', 2),
    status: 'confirmed',
  });
  sync.undoRemove(mark);
  await vi.advanceTimersByTimeAsync(2000);
  expect(marks.get('d1')).toMatchObject({ source: 'dictation', status: 'confirmed' });
  expect(sync.getSnapshot().marks).toMatchObject([
    { source: 'dictation', status: 'confirmed', saved: true },
  ]);
});

test('undo_during_an_in_flight_dictation_removal_restores_it_once_the_removal_lands', async () => {
  const initial = suggested('d1', 2);
  const { transport, marks } = fakeServer([initial]);
  let finishDelete!: () => void;
  transport.remove.mockImplementationOnce(async (id: string) => {
    await new Promise<void>((resolve) => {
      finishDelete = resolve;
    });
    marks.delete(id);
  });
  const sync = make(transport, memoryStorage(), [initial]);
  const mark = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  sync.flush();
  sync.undoRemove(mark);
  expect(sync.getSnapshot().marks).toMatchObject([{ source: 'dictation', status: 'suggested' }]);
  finishDelete();
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.create).not.toHaveBeenCalled();
  expect(marks.get('d1')).toMatchObject({ source: 'dictation', status: 'suggested' });
});

test('an_unsent_dictation_undo_survives_a_reload_and_is_sent_then', async () => {
  const { transport, marks, storage, sync, mark } = await removedAndSaved(suggested('d1', 2));
  sync.undoRemove(mark);
  closeTab();
  const reloaded = make(transport, storage, [...marks.values()]);
  expect(reloaded.getSnapshot().marks).toMatchObject([
    { id: 'd1', source: 'dictation', status: 'suggested', saved: false },
  ]);
  await vi.advanceTimersByTimeAsync(2000);
  expect(marks.get('d1')).toMatchObject({ source: 'dictation', status: 'suggested' });
  expect(reloaded.getSnapshot().hasPendingChanges).toBe(false);
});

test('a_dictation_undo_on_words_marked_again_since_shows_the_mark_they_have', async () => {
  const { marks, sync, mark } = await removedAndSaved(suggested('d1', 2));
  marks.set('m9', { ...saved('m9', 2), word_to: 2 }); // marked by hand in another tab
  sync.undoRemove(mark);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'm9', source: 'manual', status: 'confirmed', saved: true },
  ]);
  expect(marks.has('d1')).toBe(false);
});

test('a_refused_dictation_undo_brings_the_mark_back_as_the_learners_own', async () => {
  const { transport, marks, sync, mark } = await removedAndSaved({
    ...suggested('d1', 2),
    note: 'linking',
  });
  transport.restore.mockRejectedValueOnce(refusal(422, 'not_a_mark_candidate'));
  sync.undoRemove(mark);
  await vi.advanceTimersByTimeAsync(4000);
  expect(marks.get('d1')).toMatchObject({ source: 'manual', status: 'confirmed', note: 'linking' });
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'd1', source: 'manual', note: 'linking', saved: true },
  ]);
});

test('removing_a_restored_dictation_mark_whose_answer_was_lost_still_deletes_it', async () => {
  const { transport, marks, sync, mark } = await removedAndSaved(suggested('d1', 2));
  transport.restore.mockImplementationOnce(async (sent) => {
    marks.set(sent.id, suggested(sent.id, sent.word_from));
    throw new TypeError('Lost answer');
  });
  sync.undoRemove(mark);
  sync.flush();
  await vi.advanceTimersByTimeAsync(0);
  expect(marks.has('d1')).toBe(true);
  sync.remove('d1');
  await vi.advanceTimersByTimeAsync(60_000); // the next offline poll
  expect(marks.has('d1')).toBe(false);
  expect(sync.getSnapshot().marks).toEqual([]);
});

test('undo_of_a_removed_manual_mark_still_makes_it_again', async () => {
  const { transport, marks, sync, mark } = await removedAndSaved(saved('m1', 2, 'linking'));
  sync.undoRemove(mark);
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.restore).not.toHaveBeenCalled();
  expect(marks.get('m1')).toMatchObject({ source: 'manual', note: 'linking' });
});

test('a_refused_dictation_removal_raced_by_undo_keeps_the_note_written_since', async () => {
  const initial = { ...suggested('d1', 0), note: 'linking' };
  const { transport, marks } = fakeServer([initial]);
  let reject!: (error: unknown) => void;
  transport.remove.mockImplementationOnce(
    () =>
      new Promise<void>((_, fail) => {
        reject = fail;
      }),
  );
  const sync = make(transport, memoryStorage(), [initial]);
  const mark = sync.getSnapshot().marks[0]!;
  sync.remove(mark.id);
  sync.flush();
  sync.undoRemove(mark);
  sync.setNote(mark.id, 'linking, then a weak form');
  reject(refusal(403, 'forbidden'));
  await vi.advanceTimersByTimeAsync(2000);
  expect(transport.restore).not.toHaveBeenCalled();
  expect(marks.get('d1')).toMatchObject({
    source: 'dictation',
    status: 'suggested',
    note: 'linking, then a weak form',
  });
  expect(sync.getSnapshot().marks).toMatchObject([
    { source: 'dictation', status: 'suggested', note: 'linking, then a weak form', saved: true },
  ]);
});

test('a_dictation_undo_after_marking_the_words_again_here_keeps_one_mark', async () => {
  const { marks, sync, mark } = await removedAndSaved(suggested('d1', 2));
  sync.add({ id: 'm9', word_from: 2, word_to: 2, at_ms: 2000, note: 'by hand' });
  await vi.advanceTimersByTimeAsync(2000);
  sync.undoRemove(mark);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sync.getSnapshot().marks).toMatchObject([
    { id: 'm9', source: 'manual', note: 'by hand', saved: true },
  ]);
  expect([...marks.keys()]).toEqual(['m9']);
});
