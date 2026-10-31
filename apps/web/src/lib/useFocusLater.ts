import { useEffect, useState, type RefObject } from 'react';

/**
 * Focus `target` once a confirmation dialog has closed and returned focus to its
 * opener. Use it when the confirmed action removes that opener (a deleted row): the
 * dialog restores focus on a timer, so this focuses on a later one and focus does not
 * drop to <body> when the row disappears.
 */
export function useFocusLater(target: RefObject<HTMLElement | null>): () => void {
  const [request, setRequest] = useState(0);
  useEffect(() => {
    if (!request) return;
    const timer = window.setTimeout(() => target.current?.focus());
    return () => window.clearTimeout(timer);
  }, [request, target]);
  return () => setRequest((count) => count + 1);
}
