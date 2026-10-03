import { useEffect, useState, useSyncExternalStore } from 'react';

import { Autosave, type AutosaveOptions, type AutosaveSnapshot } from './autosave';

export interface AutosaveHandle<T> extends AutosaveSnapshot<T> {
  /** Record an edit: copied to this device now, sent after the debounce. */
  update: (value: T) => void;
  /** Send now, for example when the field loses focus. */
  flush: () => void;
  /** After a conflict: save this tab's value over the other one. */
  keepMine: () => void;
  /** After a conflict: take the other value and drop this tab's edits. */
  takeTheirs: () => void;
}

/**
 * Autosave bound to a component (see `Autosave`). The options are read once, when the
 * component mounts; mount it with a `key` per record so a new record starts afresh.
 */
export function useAutosave<T>(options: AutosaveOptions<T>): AutosaveHandle<T> {
  const [autosave] = useState(() => new Autosave(options));
  useEffect(() => {
    autosave.start();
    return () => autosave.stop();
  }, [autosave]);
  const snapshot = useSyncExternalStore(autosave.subscribe, autosave.getSnapshot);
  return {
    ...snapshot,
    update: (value) => autosave.update(value),
    flush: () => autosave.flush(),
    keepMine: () => autosave.keepMine(),
    takeTheirs: () => autosave.takeTheirs(),
  };
}
