import { useEffect, useState, useSyncExternalStore } from 'react';

import {
  MarkSync,
  type MarkSyncOptions,
  type MarkSyncSnapshot,
  type NewLocalMark,
} from './markSync';

export interface MarkSyncHandle extends MarkSyncSnapshot {
  add: (mark: NewLocalMark) => void;
  setNote: (id: string, note: string | null) => void;
  remove: (id: string) => void;
}

/**
 * `MarkSync` bound to a component. The options are read once, when it mounts; mount it
 * with a `key` per session so another session starts afresh.
 */
export function useMarkSync(options: MarkSyncOptions): MarkSyncHandle {
  const [sync] = useState(() => new MarkSync(options));
  useEffect(() => {
    sync.start();
    return () => sync.stop();
  }, [sync]);
  const snapshot = useSyncExternalStore(sync.subscribe, sync.getSnapshot);
  return {
    ...snapshot,
    add: (mark) => sync.add(mark),
    setNote: (id, note) => sync.setNote(id, note),
    remove: (id) => sync.remove(id),
  };
}
