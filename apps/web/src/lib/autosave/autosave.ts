import { ApiError } from '../../api/client';

/**
 * Autosave for drafts and marks (#50; FR-PL-6, NFR-REL-1, NFR-PERF-3; System Design
 * 9.3 and 11.1; ADR 0025).
 *
 * - Edits are sent 2 s after the last keystroke (debounced), one request at a time.
 * - Every save names the version it was based on. The server refuses a stale one, and
 *   the save function turns that refusal into a `SaveConflict` carrying the server's
 *   value, so two tabs never silently overwrite each other: autosave stops and asks.
 * - Every edit is copied to the browser at once (localStorage), so a reload, a closed
 *   tab or a lost connection loses nothing. The copy is restored on the next visit
 *   when it is newer than the server's value, and dropped once the server has it.
 * - A save that fails for the network waits for the connection to return; a 503
 *   (or other temporary server error) is resent after its Retry-After, or after a
 *   growing pause. Other refusals stop autosave until the next edit.
 *
 * Framework-free; `useAutosave` binds it to React.
 */

export interface SaveResult {
  /** The server's version after the save; the next save is based on it. */
  version: number;
  savedAt?: Date;
}

/** Saves `value` if the server still holds `baseVersion`; throws `SaveConflict` if not. */
export type SaveFn<T> = (value: T, baseVersion: number) => Promise<SaveResult>;

/** The server holds a newer value than the one this edit was based on. */
export class SaveConflict<T> extends Error {
  readonly value: T;
  readonly version: number;

  constructor(value: T, version: number) {
    super('The saved value changed elsewhere.');
    this.name = 'SaveConflict';
    this.value = value;
    this.version = version;
  }
}

export type AutosaveStatus<T> =
  /** Everything is on the server. `at` is the last save in this visit, if any. */
  | { kind: 'saved'; at: Date | null }
  /** Edits are waiting for the debounce. */
  | { kind: 'pending' }
  | { kind: 'saving' }
  /** No connection: edits are kept on this device and sent when it returns. */
  | { kind: 'offline' }
  /** The server is busy or down: edits are kept here and resent at `retryAt` (epoch ms). */
  | { kind: 'retrying'; retryAt: number }
  /** Changed elsewhere: autosave waits until the learner keeps theirs or takes the other. */
  | { kind: 'conflict'; theirs: T; theirVersion: number }
  /** Refused for another reason (for example too long); the next edit tries again. */
  | { kind: 'failed'; error: unknown };

export interface AutosaveSnapshot<T> {
  value: T;
  version: number;
  status: AutosaveStatus<T>;
  /** True when this visit started from an unsaved copy kept on this device. */
  restored: boolean;
}

/** The parts of `Storage` the helper uses; null keeps no local copy. */
export type LocalStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export interface AutosaveOptions<T> {
  /** Where the local copy lives, unique per record (for example per attempt). */
  storageKey: string;
  /** The value and version the server returned when the page loaded. */
  value: T;
  version: number;
  save: SaveFn<T>;
  debounceMs?: number;
  storage?: LocalStore | null;
  equals?: (a: T, b: T) => boolean;
  /** Pause before resend number `attempt` (1, 2, ...) when no Retry-After was given. */
  backoffMs?: (attempt: number) => number;
  /** How often to try again while offline, in case no `online` event arrives. */
  offlinePollMs?: number;
  isOnline?: () => boolean;
  now?: () => number;
}

interface LocalCopy<T> {
  value: T;
  baseVersion: number;
}

export const DEBOUNCE_MS = 2000;

export function defaultBackoff(attempt: number): number {
  return Math.min(30_000, 2000 * 2 ** (attempt - 1));
}

function defaultStorage(): LocalStore | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null; // blocked site data
  }
}

type Failure = { kind: 'offline' } | { kind: 'retry'; afterMs: number | null } | { kind: 'fail' };

/** What a failed save means: no connection, a temporary server error, or a refusal. */
export function classifyFailure(error: unknown): Failure {
  if (error instanceof ApiError) {
    const status = error.problem.status;
    if (status === 429 || status >= 500) {
      const after = error.retryAfterSeconds;
      return { kind: 'retry', afterMs: after === null ? null : after * 1000 };
    }
    return { kind: 'fail' };
  }
  // fetch rejects with a TypeError when the request never got an answer.
  return { kind: 'offline' };
}

export class Autosave<T> {
  private value: T;
  private version: number;
  private status: AutosaveStatus<T>;
  private restored = false;
  private snapshot: AutosaveSnapshot<T>;

  /** True while the value differs from what the server holds. */
  private dirty = false;
  private inFlight = false;
  private retries = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private readonly listeners = new Set<() => void>();

  private readonly options: Required<Omit<AutosaveOptions<T>, 'storage'>> & {
    storage: LocalStore | null;
  };

  constructor(options: AutosaveOptions<T>) {
    this.options = {
      debounceMs: DEBOUNCE_MS,
      equals: Object.is,
      backoffMs: defaultBackoff,
      offlinePollMs: 15_000,
      isOnline: () => (typeof navigator === 'undefined' ? true : navigator.onLine),
      now: () => Date.now(),
      ...options,
      storage: options.storage === undefined ? defaultStorage() : options.storage,
    };
    this.value = options.value;
    this.version = options.version;
    this.status = { kind: 'saved', at: null };

    const local = this.readLocal();
    if (local && !this.options.equals(local.value, options.value)) {
      this.value = local.value;
      this.restored = true;
      this.dirty = true;
      if (local.baseVersion === options.version) {
        // Edits that never reached the server (a reload, a closed tab, offline).
        this.status = { kind: 'pending' };
      } else {
        // The server moved on since these edits: another tab or browser saved. The
        // edits stay based on their old version until the learner chooses.
        this.version = local.baseVersion;
        this.status = { kind: 'conflict', theirs: options.value, theirVersion: options.version };
      }
    } else if (local) {
      this.removeLocal();
    }
    this.snapshot = this.makeSnapshot();
  }

  // -- reading --------------------------------------------------------------------------

  getSnapshot = (): AutosaveSnapshot<T> => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  // -- lifecycle ------------------------------------------------------------------------

  /** Start timers and listen for the connection; call once mounted. */
  start(): void {
    if (this.running) return;
    this.running = true;
    if (typeof window !== 'undefined') window.addEventListener('online', this.onOnline);
    if (this.dirty && this.status.kind === 'pending') this.schedule(0);
  }

  /** Stop timers; unsent edits are sent once more now and stay on this device anyway. */
  stop(): void {
    if (!this.running) return;
    this.running = false;
    if (typeof window !== 'undefined') window.removeEventListener('online', this.onOnline);
    this.clearTimer();
    if (this.dirty && !this.inFlight && this.status.kind !== 'conflict') {
      const sent = this.value;
      this.options.save(sent, this.version).then(
        (result) => {
          if (!this.running && this.options.equals(this.value, sent)) {
            this.version = result.version;
            this.dirty = false;
            this.removeLocal();
          }
        },
        () => undefined, // the local copy is restored on the next visit
      );
    }
  }

  // -- writing --------------------------------------------------------------------------

  /** The learner changed the value: keep a local copy now, save after the debounce. */
  update(value: T): void {
    if (this.options.equals(value, this.value)) return;
    this.value = value;
    this.dirty = true;
    this.writeLocal();
    const kind = this.status.kind;
    if (kind === 'conflict') {
      this.emit();
      return; // nothing is saved until the learner chooses
    }
    if (kind === 'offline' || kind === 'retrying') {
      this.emit(); // the pending resend takes the newest value
      return;
    }
    this.status = this.inFlight ? { kind: 'saving' } : { kind: 'pending' };
    this.emit();
    if (!this.inFlight) this.schedule(this.options.debounceMs);
  }

  /** Save now instead of after the debounce (for example when the text area loses focus). */
  flush(): void {
    const kind = this.status.kind;
    if (!this.dirty || this.inFlight || kind === 'conflict') return;
    this.clearTimer();
    void this.send();
  }

  /** Resolve a conflict by saving this tab's value over the other one. */
  keepMine(): void {
    if (this.status.kind !== 'conflict') return;
    this.version = this.status.theirVersion;
    this.dirty = true;
    this.writeLocal();
    this.status = { kind: 'pending' };
    this.emit();
    this.clearTimer();
    void this.send();
  }

  /** Resolve a conflict by taking the other value and dropping this tab's edits. */
  takeTheirs(): void {
    if (this.status.kind !== 'conflict') return;
    this.value = this.status.theirs;
    this.version = this.status.theirVersion;
    this.dirty = false;
    this.removeLocal();
    this.status = { kind: 'saved', at: null };
    this.emit();
  }

  // -- internals ------------------------------------------------------------------------

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

  private async send(): Promise<void> {
    if (!this.dirty || this.inFlight || this.status.kind === 'conflict') return;
    if (!this.options.isOnline()) {
      this.setOffline();
      return;
    }
    const sent = this.value;
    this.inFlight = true;
    this.status = { kind: 'saving' };
    this.emit();
    try {
      const result = await this.options.save(sent, this.version);
      this.inFlight = false;
      this.retries = 0;
      this.version = result.version;
      if (this.options.equals(this.value, sent)) {
        this.dirty = false;
        this.removeLocal();
        this.status = { kind: 'saved', at: result.savedAt ?? new Date(this.options.now()) };
      } else {
        this.writeLocal(); // newer edits, now based on the new version
        this.status = { kind: 'pending' };
        this.schedule(this.options.debounceMs);
      }
    } catch (error) {
      this.inFlight = false;
      this.onFailure(error);
    }
    this.emit();
  }

  private onFailure(error: unknown): void {
    if (error instanceof SaveConflict) {
      const conflict = error as SaveConflict<T>;
      this.status = { kind: 'conflict', theirs: conflict.value, theirVersion: conflict.version };
      return;
    }
    const failure = classifyFailure(error);
    if (failure.kind === 'offline') {
      this.setOffline();
    } else if (failure.kind === 'retry') {
      this.retries += 1;
      const wait = failure.afterMs ?? this.options.backoffMs(this.retries);
      this.status = { kind: 'retrying', retryAt: this.options.now() + wait };
      this.schedule(wait);
    } else {
      this.status = { kind: 'failed', error };
    }
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

  private makeSnapshot(): AutosaveSnapshot<T> {
    return {
      value: this.value,
      version: this.version,
      status: this.status,
      restored: this.restored,
    };
  }

  private readLocal(): LocalCopy<T> | null {
    try {
      const raw = this.options.storage?.getItem(this.options.storageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as Partial<LocalCopy<T>>;
      if (typeof parsed.baseVersion !== 'number' || !('value' in parsed)) return null;
      return parsed as LocalCopy<T>;
    } catch {
      return null;
    }
  }

  private writeLocal(): void {
    try {
      const copy: LocalCopy<T> = { value: this.value, baseVersion: this.version };
      this.options.storage?.setItem(this.options.storageKey, JSON.stringify(copy));
    } catch {
      // Storage full or blocked: the server save still runs.
    }
  }

  private removeLocal(): void {
    try {
      this.options.storage?.removeItem(this.options.storageKey);
    } catch {
      // Blocked site data: nothing was stored either.
    }
  }
}
