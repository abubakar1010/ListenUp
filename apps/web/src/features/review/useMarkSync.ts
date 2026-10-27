import { useEffect, useState, useSyncExternalStore } from 'react';

import {
  MarkSync,
  type MarkSyncOptions,
  type MarkDraft,
  type MarkTag,
  type MarkSyncSnapshot,
  type NewLocalMark,
  type OtherMark,
} from './markSync';

export interface MarkSyncHandle extends MarkSyncSnapshot {
  add: (mark: MarkDraft) => void;
  undoRemove: (mark: NewLocalMark) => void;
  setNote: (id: string, note: string | null) => void;
  setTag: (id: string, tag: MarkTag | null) => void;
  confirm: (id: string) => void;
  remove: (id: string) => void;
  takeSaved: (marks: OtherMark[]) => void;
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
    undoRemove: (mark) => sync.undoRemove(mark),
    setNote: (id, note) => sync.setNote(id, note),
    setTag: (id, tag) => sync.setTag(id, tag),
    confirm: (id) => sync.confirm(id),
    remove: (id) => sync.remove(id),
    takeSaved: (marks) => sync.takeSaved(marks),
  };
}
