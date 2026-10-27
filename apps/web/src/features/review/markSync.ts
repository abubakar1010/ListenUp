import { ApiError } from '../../api/client';
import type { components } from '../../api/schema';
import {
  DEBOUNCE_MS,
  classifyFailure,
  defaultBackoff,
  type AutosaveStatus,
  type LocalStore,
} from '../../lib/autosave';

/**
 * Marks made in Transcript, shown at once and saved in the background (#58; FR-TR-2,
 * NFR-PERF-3, NFR-REL-1; ADR 0033 and 0047).
 *
 * The autosave rules of `lib/autosave`, applied to a set of marks instead of one value:
 *
 * - A mark appears the moment it is made, and every change is copied to the browser at
 *   once (localStorage), so a reload, a closed tab or a lost connection loses nothing.
 * - Changes go to the server 2 s after the last one, one request at a time. A new mark
 *   carries the id made here, so a create resent after a lost answer is not doubled.
 * - Changes to one mark are merged before sending: a note written before the first save
 *   travels with the create, and an unsent mark that is removed is never sent.
 * - No connection: wait for it; a busy server: try again after a pause. A refused new
 *   mark is taken back; a refused note change or removal puts back what the server holds,
 *   so a saved mark never disappears. Signed out: every change stays on the device until
 *   the learner is back. Words already marked in another tab show that tab's mark.
 *
 * Marks are per-row changes, so there is no version conflict to resolve: the last note
 * saved wins. Framework-free; `useMarkSync` binds it to React.
 *
 * Marks added from Dictation arrive `suggested` (#59, FR-TR-3): the learner confirms or
 * removes each. Both are single deliberate actions, so they go to the server at once
 * rather than after the debounce, and are saved within a second. A note and a
 * confirmation waiting on one mark are both sent. Undo of a removed Dictation mark brings
 * it back through the Dictation route, which checks the words against the scored diff, so
 * it keeps its source (ADR 0058).
 *
 * A tag (#61, FR-TR-4) is part of the same `update` as the note: it waits for the debounce,
 * so moving through the tag choices sends only the last one, and travels with an unsent
 * create. A refused tag puts back the server's tag (ADR 0067).
 */

export type SavedMark = components['schemas']['Mark'];
export type MarkTag = NonNullable<SavedMark['tag']>;

export interface MarkTransport {
  create(mark: {
    id: string;
    word_from: number;
    word_to: number;
    note: string | null;
    tag: MarkTag | null;
  }): Promise<SavedMark>;
  setNote(id: string, note: string | null): Promise<SavedMark>;
  setTag(id: string, tag: MarkTag | null): Promise<SavedMark>;
  confirm(id: string): Promise<SavedMark>;
  /** Add the words again from Dictation; words already marked give back that mark. */
  restore(mark: { id: string; word_from: number; word_to: number }): Promise<OtherMark>;
  remove(id: string): Promise<void>;
  list(): Promise<SavedMark[]>;
}

/** A mark as the screen shows it; `saved` is false until the server has this version. */
export interface LocalMark {
  id: string;
  word_from: number;
  word_to: number;
  at_ms: number;
  note: string | null;
  tag: MarkTag | null;
  source: SavedMark['source'];
  status: SavedMark['status'];
  saved: boolean;
}

export type NewLocalMark = Omit<LocalMark, 'saved'>;

/** A mark from the Dictation route, which has no tag: it starts untagged. */
export type OtherMark = Omit<NewLocalMark, 'tag'> & { tag?: MarkTag | null };

/** A mark made here: the learner's own, so it is confirmed from the start; untagged unless
 * Undo brings back a tagged one. */
export type MarkDraft = Omit<NewLocalMark, 'source' | 'status' | 'tag'> & {
  tag?: MarkTag | null;
};

export type MarkSyncStatus = AutosaveStatus<never>;

export interface MarkSyncSnapshot {
  marks: LocalMark[];
  status: MarkSyncStatus;
  /** Includes pending removals, which are absent from the visible marks. */
  hasPendingChanges: boolean;
  /** True when this visit started from unsent changes kept on this device. */
  restored: boolean;
}

export interface MarkSyncOptions {
  /** Where the unsent changes live, one key per session. */
  storageKey: string;
  /** The marks the server returned when the page loaded. */
  marks: SavedMark[];
  transport: MarkTransport;
  debounceMs?: number;
  storage?: LocalStore | null;
  backoffMs?: (attempt: number) => number;
  offlinePollMs?: number;
  isOnline?: () => boolean;
  now?: () => number;
}

/**
 * `update`: the note, the tag or the status differs from the server's. `restore`: Undo of a
 * removed Dictation mark, added again from Dictation.
 */
type Op = 'none' | 'create' | 'restore' | 'update' | 'delete';

interface Entry {
  mark: NewLocalMark;
  op: Op;
  /** Counts local changes, so a save that finished can tell whether it is still current. */
  rev: number;
  /** The mark as the server last held it; null while the server may not have it yet. */
  server: NewLocalMark | null;
  /**
   * True once a create for this mark has been sent. Its answer may have been lost, so
   * the server may hold the mark and a removal has to be sent too.
   */
  attempted: boolean;
  /** A lost DELETE response may still mean the server removed this mark. */
  deleteAttempted?: boolean;
  /** A tag request may have landed without an answer; resend even if it matches server. */
  tagUncertain?: boolean;
}

/**
 * A copy kept before marks had a source (#59) has none: it is the learner's own. One kept
 * before tags (#61) has no tag, which is no tag change.
 */
type StoredMark = MarkDraft & Partial<Pick<NewLocalMark, 'source' | 'status'>>;

interface StoredCopy {
  ops: { op: Exclude<Op, 'none'>; mark: StoredMark; attempted?: boolean }[];
}

function fromServer(mark: SavedMark | OtherMark): Entry {
  return { mark: local(mark), op: 'none', rev: 0, server: local(mark), attempted: false };
}

function local(mark: SavedMark | OtherMark): NewLocalMark {
  const { id, word_from, word_to, at_ms, note, source, status } = mark;
  return { id, word_from, word_to, at_ms, note, tag: mark.tag ?? null, source, status };
}

/** True when the learner's version of a mark has something the server's lacks. */
function differs(mark: NewLocalMark, server: NewLocalMark): boolean {
  return mark.note !== server.note || mark.tag !== server.tag || needsConfirm(mark, server);
}

function needsConfirm(mark: NewLocalMark, server: NewLocalMark): boolean {
  return mark.status === 'confirmed' && server.status !== 'confirmed';
}

function defaultStorage(): LocalStore | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null; // blocked site data
  }
}

export class MarkSync {
  private readonly entries = new Map<string, Entry>();
  private status: MarkSyncStatus = { kind: 'saved', at: null };
  private restored = false;
  private snapshot: MarkSyncSnapshot;
  private inFlight = false;
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private readonly listeners = new Set<() => void>();
  private readonly options: Required<Omit<MarkSyncOptions, 'storage'>> & {
    storage: LocalStore | null;
  };

  constructor(options: MarkSyncOptions) {
    this.options = {
      debounceMs: DEBOUNCE_MS,
      backoffMs: defaultBackoff,
      offlinePollMs: 15_000,
      isOnline: () => (typeof navigator === 'undefined' ? true : navigator.onLine),
      now: () => Date.now(),
      ...options,
      storage: options.storage === undefined ? defaultStorage() : options.storage,
    };
    for (const mark of options.marks) this.entries.set(mark.id, fromServer(mark));
    this.restore();
    this.snapshot = this.makeSnapshot();
  }

  // -- reading --------------------------------------------------------------------------

  getSnapshot = (): MarkSyncSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  // -- lifecycle ------------------------------------------------------------------------

  start(): void {
    if (this.running) return;
    this.running = true;
    if (typeof window !== 'undefined') window.addEventListener('online', this.onOnline);
    if (this.status.kind === 'pending') this.schedule(0);
  }

  /** Stop timers and send what is left once; it stays on this device anyway. */
  stop(): void {
    if (!this.running) return;
    this.running = false;
    if (typeof window !== 'undefined') window.removeEventListener('online', this.onOnline);
    this.clearTimer();
    if (!this.inFlight) void this.send();
  }

  // -- writing --------------------------------------------------------------------------

  /**
   * A new mark, or Undo of a removal. A removal that never reached the server is
   * cancelled and the mark keeps its source; one that did makes the mark again as the
   * learner's own (`manual`, confirmed). Undo of a Dictation mark goes through
   * `undoRemove`, which keeps its source.
   */
  add(draft: MarkDraft): void {
    const previous = this.entries.get(draft.id);
    // Undo of a queued deletion cancels it. Keep the server snapshot so a refused
    // unsaved note rolls back to the saved mark, rather than removing it as new.
    if (previous?.op === 'delete' && previous.server && !previous.deleteAttempted) {
      previous.mark = { ...previous.mark, note: draft.note, tag: draft.tag ?? previous.mark.tag };
      previous.op = differs(previous.mark, previous.server) ? 'update' : 'none';
      previous.rev += 1;
      this.changed();
      return;
    }
    const mark: NewLocalMark = {
      id: draft.id,
      word_from: draft.word_from,
      word_to: draft.word_to,
      at_ms: draft.at_ms,
      note: draft.note,
      tag: draft.tag ?? null,
      source: 'manual',
      status: 'confirmed',
    };
    this.entries.set(mark.id, {
      mark,
      op: 'create',
      rev: 1,
      server: null,
      // Undo may replace a queued deletion of a mark the server already holds.
      // Removing it again must still DELETE, even before this create is sent.
      attempted: previous !== undefined && (previous.attempted || previous.server !== null),
    });
    this.changed();
  }

  /**
   * Undo of a removal. A Dictation mark whose removal may have reached the server is added
   * again from Dictation, so it comes back as it was rather than as the learner's own
   * (ADR 0058); its note and a confirmation follow as an update.
   */
  undoRemove(mark: NewLocalMark): void {
    const previous = this.entries.get(mark.id);
    const unsent = previous?.op === 'delete' && previous.server && !previous.deleteAttempted;
    if (mark.source !== 'dictation' || unsent) return this.add(mark);
    this.entries.set(mark.id, {
      mark: local(mark),
      op: 'restore',
      rev: 1,
      server: null,
      // The removal may land before this is sent: removing it again must still DELETE.
      attempted: true,
    });
    this.changed();
  }

  setNote(id: string, note: string | null): void {
    const entry = this.entries.get(id);
    if (!entry || entry.op === 'delete' || entry.mark.note === note) return;
    entry.mark = { ...entry.mark, note };
    entry.rev += 1;
    if (entry.op === 'none') entry.op = 'update';
    this.changed();
  }

  /** FR-TR-4: set, change or clear (null) the tag; sent after the debounce like a note. */
  setTag(id: string, tag: MarkTag | null): void {
    const entry = this.entries.get(id);
    if (!entry || entry.op === 'delete' || entry.mark.tag === tag) return;
    entry.mark = { ...entry.mark, tag };
    entry.rev += 1;
    if (entry.op === 'none') entry.op = 'update';
    // Keep an update queued even when changed back: an in-flight request may store
    // the intermediate value, and its response may never arrive. sendUpdate skips
    // unchanged fields when no request has been sent.
    this.changed();
  }

  /** FR-TR-3: keep a suggested Dictation mark; sent at once. */
  confirm(id: string): void {
    const entry = this.entries.get(id);
    if (!entry || entry.op === 'delete' || entry.mark.status === 'confirmed') return;
    entry.mark = { ...entry.mark, status: 'confirmed' };
    entry.rev += 1;
    if (entry.op === 'none') entry.op = 'update';
    this.changed(0);
  }

  remove(id: string): void {
    const entry = this.entries.get(id);
    if (!entry || entry.op === 'delete') return;
    entry.deleteAttempted = false;
    entry.rev += 1;
    // A create that was never sent leaves nothing behind. One that was sent may have
    // reached the server even though its answer was lost, so the removal must be sent.
    if ((entry.op === 'create' || entry.op === 'restore') && !entry.attempted)
      this.entries.delete(id);
    else entry.op = 'delete';
    this.changed(0);
  }

  /**
   * Marks the server already holds that were made elsewhere on this page: the Dictation
   * result beside the transcript adds them through its own route (#55). Nothing is sent,
   * and a mark this tab already has keeps this tab's version.
   */
  takeSaved(marks: OtherMark[]): void {
    const fresh = marks.filter((mark) => !this.entries.has(mark.id));
    for (const mark of fresh) this.entries.set(mark.id, fromServer(mark));
    if (fresh.length > 0) this.emit();
  }

  /** Send now instead of after the debounce. */
  flush(): void {
    if (this.inFlight || !this.next()) return;
    this.clearTimer();
    void this.send();
  }

  // -- internals ------------------------------------------------------------------------

  /** A local change: keep it on the device and send it after `delayMs`. */
  private changed(delayMs = this.options.debounceMs): void {
    this.writeLocal();
    const kind = this.status.kind;
    if (kind !== 'offline' && kind !== 'retrying') {
      if (!this.next()) this.status = { kind: 'saved', at: null };
      else this.status = this.inFlight ? { kind: 'saving' } : { kind: 'pending' };
      if (!this.inFlight && this.next()) this.schedule(delayMs);
    }
    this.emit();
  }

  private next(): Entry | undefined {
    for (const entry of this.entries.values()) if (entry.op !== 'none') return entry;
    return undefined;
  }

  private onOnline = () => {
    if (this.status.kind === 'offline' || this.status.kind === 'retrying') {
      this.clearTimer();
      void this.send();
    }
  };

  private schedule(ms: number): void {
    this.clearTimer();
    if (!this.running) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.send();
    }, ms);
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  /** Send the waiting changes one after the other until none is left or one fails. */
  private async send(): Promise<void> {
    if (this.inFlight) return;
    if (!this.next()) {
      if (this.status.kind !== 'saved') {
        this.status = { kind: 'saved', at: new Date(this.options.now()) };
        this.emit();
      }
      return;
    }
    if (!this.options.isOnline()) {
      this.setOffline();
      return;
    }
    this.inFlight = true;
    this.status = { kind: 'saving' };
    this.emit();
    let entry: Entry | undefined;
    try {
      while ((entry = this.next())) {
        await this.sendOne(entry);
        this.writeLocal();
        this.emit();
      }
      this.inFlight = false;
      this.retries = 0;
      this.status = { kind: 'saved', at: new Date(this.options.now()) };
    } catch (error) {
      this.inFlight = false;
      this.onFailure(error, entry);
      this.writeLocal();
    }
    this.emit();
  }

  private async sendOne(entry: Entry): Promise<void> {
    const { mark, op, rev } = entry;
    if (op === 'create') {
      entry.attempted = true;
      this.writeLocal(); // kept before the request: the tab may close while it is on its way
      const stored = await this.options.transport.create({
        id: mark.id,
        word_from: mark.word_from,
        word_to: mark.word_to,
        note: mark.note,
        tag: mark.tag,
      });
      this.settled(entry, rev, local(stored));
      // A resend after a lost answer gets the mark the server already held, with the note
      // and tag it had then: the ones written since still have to go.
      if (entry.op === 'none' && (stored.note !== mark.note || (stored.tag ?? null) !== mark.tag)) {
        entry.mark = { ...entry.mark, note: mark.note, tag: mark.tag };
        entry.op = 'update';
      }
    } else if (op === 'restore') {
      await this.sendRestore(entry);
    } else if (op === 'update') {
      await this.sendUpdate(entry, rev);
    } else {
      entry.deleteAttempted = true;
      await this.gone(() => this.options.transport.remove(mark.id));
      // Undo can replace this entry while DELETE is in flight. Keep that new create
      // queued until deletion settles, then recreate the mark (including its note).
      if (this.entries.get(mark.id) === entry) this.entries.delete(mark.id);
    }
  }

  /**
   * Send what differs from the server: the note, the tag, then the confirmation. Each answer
   * becomes the server's version at once, so a failure between the two resends only
   * what is left and a refusal puts back what the server really holds.
   */
  private async sendUpdate(entry: Entry, rev: number): Promise<void> {
    const { mark } = entry;
    let server = entry.server ?? mark;
    if (!entry.server || mark.note !== server.note) {
      const stored = await this.gone(() => this.options.transport.setNote(mark.id, mark.note));
      if (!stored) return void this.entries.delete(mark.id);
      server = entry.server = local(stored);
    }
    if (entry.tagUncertain || mark.tag !== server.tag) {
      // Until the answer arrives, the server may hold either tag. On a lost answer,
      // retry the learner's value rather than trusting the pre-request snapshot.
      entry.tagUncertain = true;
      const stored = await this.gone(() => this.options.transport.setTag(mark.id, mark.tag));
      if (!stored) return void this.entries.delete(mark.id);
      entry.tagUncertain = false;
      server = entry.server = local(stored);
    }
    if (needsConfirm(mark, server)) {
      const stored = await this.gone(() => this.options.transport.confirm(mark.id));
      if (!stored) return void this.entries.delete(mark.id);
      server = local(stored);
    }
    this.settled(entry, rev, server);
  }

  /**
   * Add a removed Dictation mark again. Words marked again since (by hand, or in another
   * tab) give back the mark they have, which then stands in for this one.
   */
  private async sendRestore(entry: Entry): Promise<void> {
    const { id, word_from, word_to } = entry.mark;
    const stored = local(await this.options.transport.restore({ id, word_from, word_to }));
    if (stored.id !== id) {
      if (this.entries.get(id) === entry) this.entries.delete(id);
      if (!this.entries.has(stored.id)) this.entries.set(stored.id, fromServer(stored));
      return;
    }
    entry.server = stored;
    if (differs(entry.mark, stored)) {
      entry.op = 'update'; // the note, or a confirmation made before the removal
    } else {
      entry.mark = stored;
      entry.op = 'none';
    }
  }

  /** The request finished: keep the server's mark unless the learner changed it since. */
  private settled(entry: Entry, rev: number, stored: NewLocalMark): void {
    entry.server = stored;
    if (entry.rev === rev) {
      entry.mark = stored;
      entry.op = 'none';
    } else if (entry.op === 'create') {
      entry.op = 'update'; // created now; the newer note still has to go
    } else if (entry.op === 'none' && differs(entry.mark, stored)) {
      // Changed back while this request was on its way: the server now holds what was
      // sent, so the learner's older value has to go again.
      entry.op = 'update';
    }
  }

  /** Run a change to a mark; a mark the server no longer has resolves to undefined. */
  private async gone<T>(request: () => Promise<T>): Promise<T | undefined> {
    try {
      return await request();
    } catch (error) {
      if (error instanceof ApiError && error.code === 'mark_not_found') return undefined;
      throw error;
    }
  }

  private onFailure(error: unknown, entry: Entry | undefined): void {
    const failure = classifyFailure(error);
    if (failure.kind === 'offline') {
      this.setOffline();
    } else if (failure.kind === 'retry') {
      this.retries += 1;
      const wait = failure.afterMs ?? this.options.backoffMs(this.retries);
      this.status = { kind: 'retrying', retryAt: this.options.now() + wait };
      this.schedule(wait);
    } else if (error instanceof ApiError && error.code === 'mark_exists' && entry) {
      this.entries.delete(entry.mark.id);
      void this.reload();
    } else if (error instanceof ApiError && error.problem.status === 401) {
      // Signed out: nothing is refused, so every change stays here (and on the device)
      // until the learner is back; the next change tries again.
      this.status = { kind: 'failed', error };
    } else {
      // Refused for good: take the change back so the queue does not stick on it.
      if (entry) this.takeBack(entry);
      this.status = { kind: 'failed', error };
      if (this.next()) this.schedule(this.options.debounceMs);
    }
  }

  /** Undo a refused change: a new mark goes; a saved mark shows what the server holds. */
  private takeBack(entry: Entry): void {
    const current = this.entries.get(entry.mark.id);
    if (current && current !== entry && entry.server) {
      // A refused in-flight DELETE left the saved mark intact. Undo may have
      // replaced its entry: reuse that known snapshot instead of recreating it.
      current.server = entry.server;
      if (current.op === 'create' || current.op === 'restore') {
        current.mark = { ...entry.server, note: current.mark.note, tag: current.mark.tag };
        current.op = differs(current.mark, entry.server) ? 'update' : 'none';
      } else this.takeBack(current);
      return;
    }
    if (entry.op === 'create') {
      this.entries.delete(entry.mark.id);
    } else if (entry.op === 'restore') {
      // The words can no longer come back from Dictation: Undo still keeps the mark, as
      // the learner's own.
      entry.mark = { ...entry.mark, source: 'manual', status: 'confirmed' };
      entry.op = 'create';
    } else if (entry.server) {
      entry.mark = entry.server;
      entry.op = 'none';
      entry.tagUncertain = false;
    } else {
      entry.op = 'create'; // a removal of a mark never confirmed: it stays, and is sent again
    }
  }

  /** Take the server's marks, keeping this tab's unsent changes on top. */
  private async reload(): Promise<void> {
    this.inFlight = true;
    try {
      const marks = await this.options.transport.list();
      this.takeServerMarks(marks);
      this.inFlight = false;
      this.status = { kind: 'pending' };
      this.emit();
      await this.send();
    } catch (error) {
      this.inFlight = false;
      this.onFailure(error, undefined);
      this.emit();
    }
  }

  /** The server's marks over the saved ones; this tab's unsent changes stay on top. */
  private takeServerMarks(marks: SavedMark[]): void {
    const onServer = new Set(marks.map((mark) => mark.id));
    for (const mark of marks) {
      const entry = this.entries.get(mark.id);
      if (!entry) this.entries.set(mark.id, fromServer(mark));
      else {
        entry.server = local(mark);
        if (entry.op === 'none') entry.mark = local(mark);
      }
    }
    for (const [id, entry] of this.entries)
      if (entry.op === 'none' && !onServer.has(id)) this.entries.delete(id);
  }

  private setOffline(): void {
    this.status = { kind: 'offline' };
    this.schedule(this.options.offlinePollMs);
    this.emit();
  }

  private emit(): void {
    this.snapshot = this.makeSnapshot();
    for (const listener of this.listeners) listener();
  }

  private makeSnapshot(): MarkSyncSnapshot {
    const marks = [...this.entries.values()]
      .filter((entry) => entry.op !== 'delete')
      .map((entry) => ({ ...entry.mark, saved: entry.op === 'none' }))
      .sort((a, b) => a.at_ms - b.at_ms || a.word_from - b.word_from || a.word_to - b.word_to);
    return {
      marks,
      status: this.status,
      hasPendingChanges: this.next() !== undefined,
      restored: this.restored,
    };
  }

  /** Lay the unsent changes kept on this device over the server's marks. */
  private restore(): void {
    const copy = this.readLocal();
    if (!copy) return;
    for (const { op, mark: kept, attempted = false } of copy.ops) {
      const mark: NewLocalMark = {
        source: 'manual',
        status: 'confirmed',
        ...kept,
        tag: kept.tag ?? null,
      };
      const entry = this.entries.get(mark.id);
      if ((op === 'create' || op === 'restore') && !entry) {
        this.entries.set(mark.id, { mark, op, rev: 1, server: null, attempted });
      } else if (!entry && op === 'delete' && attempted) {
        // The page's list may predate a create that landed late: send the removal anyway.
        this.entries.set(mark.id, { mark, op: 'delete', rev: 1, server: null, attempted });
      } else if (entry && op === 'delete') {
        entry.op = 'delete';
        entry.rev = 1;
      } else if (entry) {
        // A confirmation kept here still counts once the server holds the mark. A kept
        // create or restore the server already holds (Undo while its DELETE was in
        // flight) is a resend: only its note and tag can be newer, and its status is not a
        // confirmation the learner made.
        const confirmed = op === 'update' && kept.status === 'confirmed';
        const next = { ...entry.mark, note: kept.note };
        if (kept.tag !== undefined) next.tag = kept.tag;
        if (confirmed) next.status = 'confirmed';
        if (differs(next, entry.mark)) {
          entry.mark = next;
          entry.op = 'update';
          entry.rev = 1;
        }
      }
      // Anything else is already on the server, or gone from it.
    }
    this.restored = this.next() !== undefined;
    if (this.restored) this.status = { kind: 'pending' };
    this.writeLocal();
  }

  private readLocal(): StoredCopy | null {
    try {
      const raw = this.options.storage?.getItem(this.options.storageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as Partial<StoredCopy>;
      return Array.isArray(parsed.ops) ? (parsed as StoredCopy) : null;
    } catch {
      return null;
    }
  }

  private writeLocal(): void {
    const ops = [...this.entries.values()]
      .filter((entry) => entry.op !== 'none')
      .map((entry) => ({
        op: entry.op as Exclude<Op, 'none'>,
        mark: entry.mark,
        ...(entry.attempted && !entry.server ? { attempted: true } : {}),
      }));
    try {
      if (ops.length === 0) this.options.storage?.removeItem(this.options.storageKey);
      else this.options.storage?.setItem(this.options.storageKey, JSON.stringify({ ops }));
    } catch {
      // Storage full or blocked: the server save still runs.
    }
  }
}
