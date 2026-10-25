import { useEffect, useRef } from 'react';

import { actionFor, stepSpeed } from './playerPolicy';
import type { PassagePlayer } from './usePassagePlayer';

/**
 * The player keys outside text fields (UX-07): Space or K, J, R, [ and ]. Keys typed
 * into a field or on another control keep their own meaning, and nothing acts while a
 * dialog is open. For screens without a text area of their own; Dictation and
 * Transcript add their own keys.
 */
export function usePlayerKeys(player: PassagePlayer) {
  const latest = useRef(player);
  useEffect(() => {
    latest.current = player;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (
        target?.closest?.(
          'input, textarea, select, button, a[href], [contenteditable="true"], [role="dialog"]',
        )
      ) {
        return;
      }
      const action = actionFor(event, false);
      const current = latest.current;
      if (!action || current.status !== 'ready') return;
      event.preventDefault();
      if (action === 'toggle') current.toggle();
      else if (action === 'back') current.back();
      else if (action === 'replay') current.replay();
      else current.setSpeed(stepSpeed(current.speed, action === 'slower' ? 1 : -1));
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
}
