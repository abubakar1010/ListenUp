import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';

import { type SaveFn, type SaveResult } from './autosave';
import { useAutosave } from './useAutosave';

const KEY = 'draft:remount';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}

function Editor({
  save,
  value = '',
  version = 0,
}: {
  save: SaveFn<string>;
  value?: string;
  version?: number;
}) {
  const draft = useAutosave({ storageKey: KEY, value, version, save });
  return (
    <>
      <textarea
        aria-label="Draft"
        value={draft.value}
        onChange={(event) => draft.update(event.target.value)}
        onBlur={draft.flush}
      />
      <p role="status">{draft.status.kind}</p>
      {draft.restored && <p>Recovered draft</p>}
    </>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  localStorage.clear();
});

test.each(['unmount flush', 'blur save'])(
  '%s acknowledgment preserves edits after unmount and remount',
  async (path) => {
    const finalSave = deferred<SaveResult>();
    const oldSave = vi.fn<SaveFn<string>>(() => finalSave.promise);
    const old = render(<Editor save={oldSave} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), {
      target: { value: 'old text' },
    });
    if (path === 'blur save') {
      fireEvent.blur(screen.getByRole('textbox', { name: 'Draft' }));
      expect(screen.getByRole('status')).toHaveTextContent('saving');
    }
    old.unmount();
    expect(oldSave).toHaveBeenCalledExactlyOnceWith('old text', 0);

    const pendingSave = deferred<SaveResult>();
    const newSave = vi.fn<SaveFn<string>>(() => pendingSave.promise);
    const newer = render(<Editor save={newSave} />);
    expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('old text');
    expect(screen.getByText('Recovered draft')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), {
      target: { value: 'newer unsaved text' },
    });
    const newerCopy = localStorage.getItem(KEY);
    expect(JSON.parse(newerCopy!)).toEqual({ value: 'newer unsaved text', baseVersion: 0 });

    await act(async () => {
      finalSave.resolve({ version: 1 });
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(localStorage.getItem(KEY)).toBe(newerCopy);
    expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('newer unsaved text');
    expect(screen.getByRole('status')).toHaveTextContent('pending');
    expect(newSave).not.toHaveBeenCalled();
    newer.unmount();
    expect(newSave).toHaveBeenCalledExactlyOnceWith('newer unsaved text', 0);

    render(<Editor save={newSave} value="old text" version={1} />);
    expect(screen.getByRole('textbox', { name: 'Draft' })).toHaveValue('newer unsaved text');
    expect(screen.getByText('Recovered draft')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('conflict');
    expect(localStorage.getItem(KEY)).toBe(newerCopy);
  },
);
