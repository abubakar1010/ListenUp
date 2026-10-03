import { ApiError, type Problem } from '../../api/client';
import { Autosave, SaveConflict, type LocalStore, type SaveFn, type SaveResult } from './autosave';

const KEY = 'draft:attempt-1';

function memoryStore(initial: Record<string, string> = {}): LocalStore & {
  data: Record<string, string>;
} {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value;
    },
    removeItem: (key) => {
      delete data[key];
    },
  };
}

function apiError(status: number, code: string, retryAfter: number | null = null): ApiError {
  const problem: Problem = { type: '', title: '', status, detail: `${code}.`, code };
  return new ApiError(problem, retryAfter);
}

interface Harness {
  autosave: Autosave<string>;
  save: ReturnType<typeof vi.fn<SaveFn<string>>>;
  store: ReturnType<typeof memoryStore>;
  online: { value: boolean };
}

/** A started autosave of a draft at `version` on the server; the save succeeds by default. */
function setup({
  value = '',
  version = 0,
  store = memoryStore(),
  save,
}: {
  value?: string;
  version?: number;
  store?: ReturnType<typeof memoryStore>;
  save?: SaveFn<string>;
} = {}): Harness {
  let serverVersion = version;
  const fn = vi.fn<SaveFn<string>>(
    save ??
      (async (): Promise<SaveResult> => {
        serverVersion += 1;
        return { version: serverVersion, savedAt: new Date('2026-10-03T10:51:00') };
      }),
  );
  const online = { value: true };
  const autosave = new Autosave<string>({
    storageKey: KEY,
    value,
    version,
    save: fn,
    storage: store,
    isOnline: () => online.value,
  });
  autosave.start();
  return { autosave, save: fn, store, online };
}

/** Let resolved promises run without moving the clock. */
async function settle() {
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('debounce', () => {
  test('edits within 2 s go out as one save of the newest text', async () => {
    const { autosave, save } = setup();

    autosave.update('So');
    await vi.advanceTimersByTimeAsync(1500);
    autosave.update('So the');
    await vi.advanceTimersByTimeAsync(1999);
    expect(save).not.toHaveBeenCalled();
    expect(autosave.getSnapshot().status.kind).toBe('pending');

    await vi.advanceTimersByTimeAsync(1);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith('So the', 0);
    expect(autosave.getSnapshot().status).toEqual({
      kind: 'saved',
      at: new Date('2026-10-03T10:51:00'),
    });
  });

  test('each save is based on the version the last one returned', async () => {
    const { autosave, save } = setup({ version: 4 });

    autosave.update('one');
    await vi.advanceTimersByTimeAsync(2000);
    autosave.update('one two');
    await vi.advanceTimersByTimeAsync(2000);

    expect(save.mock.calls).toEqual([
      ['one', 4],
      ['one two', 5],
    ]);
    expect(autosave.getSnapshot().version).toBe(6);
  });

  test('typing during a save sends the newer text after it, on the new version', async () => {
    let finish: (result: SaveResult) => void = () => undefined;
    const { autosave, save } = setup({
      save: () => new Promise<SaveResult>((resolve) => (finish = resolve)),
    });
    autosave.update('first');
    await vi.advanceTimersByTimeAsync(2000);

    autosave.update('first and more');
    expect(autosave.getSnapshot().status.kind).toBe('saving');
    finish({ version: 1 });
    await settle();
    expect(autosave.getSnapshot().status.kind).toBe('pending');
    await vi.advanceTimersByTimeAsync(2000);

    expect(save.mock.calls).toEqual([
      ['first', 0],
      ['first and more', 1],
    ]);
  });

  test('flush saves at once', async () => {
    const { autosave, save } = setup();
    autosave.update('typed');

    autosave.flush();
    await settle();

    expect(save).toHaveBeenCalledWith('typed', 0);
  });

  test('an unchanged value is not saved', async () => {
    const { autosave, save } = setup({ value: 'same' });

    autosave.update('same');
    await vi.advanceTimersByTimeAsync(5000);

    expect(save).not.toHaveBeenCalled();
  });
});

describe('local copy', () => {
  test('every edit is kept on this device until the server has it', async () => {
    const { autosave, store } = setup({ version: 2 });

    autosave.update('not yet sent');

    expect(JSON.parse(store.data[KEY]!)).toEqual({ value: 'not yet sent', baseVersion: 2 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(store.data[KEY]).toBeUndefined();
  });

  test('a reload restores unsent edits and sends them at once', async () => {
    const store = memoryStore({
      [KEY]: JSON.stringify({ value: 'typed then reloaded', baseVersion: 3 }),
    });

    const { autosave, save } = setup({ value: 'typed', version: 3, store });

    expect(autosave.getSnapshot()).toMatchObject({ value: 'typed then reloaded', restored: true });
    await settle();
    expect(save).toHaveBeenCalledWith('typed then reloaded', 3);
  });

  test('a copy older than the server is a conflict, not a silent overwrite', async () => {
    const store = memoryStore({ [KEY]: JSON.stringify({ value: 'this browser', baseVersion: 1 }) });

    const { autosave, save } = setup({ value: 'another browser', version: 5, store });
    await vi.advanceTimersByTimeAsync(5000);

    expect(save).not.toHaveBeenCalled();
    expect(autosave.getSnapshot()).toMatchObject({
      value: 'this browser',
      status: { kind: 'conflict', theirs: 'another browser', theirVersion: 5 },
    });
  });

  test('a copy equal to the server value is dropped', () => {
    const store = memoryStore({ [KEY]: JSON.stringify({ value: 'same', baseVersion: 1 }) });

    const { autosave } = setup({ value: 'same', version: 2, store });

    expect(autosave.getSnapshot().restored).toBe(false);
    expect(store.data[KEY]).toBeUndefined();
  });

  test('a broken copy is ignored', () => {
    const store = memoryStore({ [KEY]: '{not json' });

    const { autosave } = setup({ value: 'server', store });

    expect(autosave.getSnapshot().value).toBe('server');
  });
});

describe('version conflicts', () => {
  function conflicted() {
    const harness = setup({
      save: vi
        .fn<SaveFn<string>>()
        .mockRejectedValueOnce(new SaveConflict('from tab two', 7))
        .mockResolvedValue({ version: 8 }),
    });
    harness.autosave.update('from tab one');
    return harness;
  }

  test('a stale save stops autosave and shows both values', async () => {
    const { autosave, save } = conflicted();
    await vi.advanceTimersByTimeAsync(2000);

    autosave.update('from tab one, still typing');
    await vi.advanceTimersByTimeAsync(10_000);

    expect(save).toHaveBeenCalledTimes(1);
    expect(autosave.getSnapshot()).toMatchObject({
      value: 'from tab one, still typing',
      status: { kind: 'conflict', theirs: 'from tab two', theirVersion: 7 },
    });
  });

  test('keeping mine saves it over the other version', async () => {
    const { autosave, save } = conflicted();
    await vi.advanceTimersByTimeAsync(2000);

    autosave.keepMine();
    await settle();

    expect(save).toHaveBeenLastCalledWith('from tab one', 7);
    expect(autosave.getSnapshot()).toMatchObject({ version: 8, status: { kind: 'saved' } });
  });

  test('taking theirs replaces my text and forgets my copy', async () => {
    const { autosave, save, store } = conflicted();
    await vi.advanceTimersByTimeAsync(2000);

    autosave.takeTheirs();

    expect(autosave.getSnapshot()).toMatchObject({
      value: 'from tab two',
      version: 7,
      status: { kind: 'saved', at: null },
    });
    expect(store.data[KEY]).toBeUndefined();
    expect(save).toHaveBeenCalledTimes(1);
  });
});

describe('offline and server errors', () => {
  test('a lost connection keeps the text and sends it when the connection returns', async () => {
    const save = vi
      .fn<SaveFn<string>>()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue({ version: 1 });
    const { autosave, store } = setup({ save });
    autosave.update('typed on the train');
    await vi.advanceTimersByTimeAsync(2000);
    expect(autosave.getSnapshot().status.kind).toBe('offline');

    autosave.update('typed on the train, in a tunnel');
    window.dispatchEvent(new Event('online'));
    await settle();

    expect(save).toHaveBeenLastCalledWith('typed on the train, in a tunnel', 0);
    expect(autosave.getSnapshot().status.kind).toBe('saved');
    expect(store.data[KEY]).toBeUndefined();
  });

  test('while the browser says it is offline, nothing is sent until it is back', async () => {
    const { autosave, save, online } = setup();
    online.value = false;
    autosave.update('offline text');
    await vi.advanceTimersByTimeAsync(2000);

    expect(save).not.toHaveBeenCalled();
    expect(autosave.getSnapshot().status.kind).toBe('offline');

    online.value = true;
    await vi.advanceTimersByTimeAsync(15_000);
    expect(save).toHaveBeenCalledWith('offline text', 0);
  });

  test('a 503 is resent after its Retry-After', async () => {
    const save = vi
      .fn<SaveFn<string>>()
      .mockRejectedValueOnce(apiError(503, 'service_unavailable', 7))
      .mockResolvedValue({ version: 1 });
    const { autosave } = setup({ save });
    autosave.update('text');
    await vi.advanceTimersByTimeAsync(2000);
    expect(autosave.getSnapshot().status.kind).toBe('retrying');

    await vi.advanceTimersByTimeAsync(6999);
    expect(save).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);

    expect(save).toHaveBeenCalledTimes(2);
    expect(autosave.getSnapshot().status.kind).toBe('saved');
  });

  test('a server error without Retry-After is resent after a growing pause', async () => {
    const save = vi
      .fn<SaveFn<string>>()
      .mockRejectedValueOnce(apiError(500, 'internal_error'))
      .mockRejectedValueOnce(apiError(502, 'bad_gateway'))
      .mockResolvedValue({ version: 1 });
    const { autosave } = setup({ save });
    autosave.update('text');
    await vi.advanceTimersByTimeAsync(2000); // first try
    await vi.advanceTimersByTimeAsync(2000); // after 2 s
    expect(save).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(3999);
    expect(save).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); // after 4 s

    expect(save).toHaveBeenCalledTimes(3);
    expect(autosave.getSnapshot().status.kind).toBe('saved');
  });

  test('a refusal is not retried until the next edit', async () => {
    const save = vi
      .fn<SaveFn<string>>()
      .mockRejectedValueOnce(apiError(422, 'draft_too_long'))
      .mockResolvedValue({ version: 1 });
    const { autosave } = setup({ save });
    autosave.update('far too long');
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(autosave.getSnapshot().status.kind).toBe('failed');

    autosave.update('shorter');
    await vi.advanceTimersByTimeAsync(2000);

    expect(save).toHaveBeenLastCalledWith('shorter', 0);
  });
});

test('stopping sends unsent edits once more', async () => {
  const { autosave, save, store } = setup();
  autosave.update('leaving the page');

  autosave.stop();
  await settle();

  expect(save).toHaveBeenCalledWith('leaving the page', 0);
  expect(store.data[KEY]).toBeUndefined();
});

test('listeners hear every change', async () => {
  const { autosave } = setup();
  const heard: string[] = [];
  autosave.subscribe(() => heard.push(autosave.getSnapshot().status.kind));

  autosave.update('a');
  await vi.advanceTimersByTimeAsync(2000);

  expect(heard).toEqual(['pending', 'saving', 'saved']);
});
