import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router';

import { focusMain } from './focusMain';

/**
 * After the learner moves to another page, puts focus on its content so the next
 * Tab starts there and screen readers read the new page. Redirects while the app
 * first loads (for example to sign in) leave focus alone, like a fresh page load,
 * so the skip link stays the first stop.
 */
export function RouteFocus() {
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  const interacted = useRef(false);

  useEffect(() => {
    const mark = () => {
      interacted.current = true;
    };
    document.addEventListener('pointerdown', mark, { once: true, capture: true });
    document.addEventListener('keydown', mark, { once: true, capture: true });
    return () => {
      document.removeEventListener('pointerdown', mark, { capture: true });
      document.removeEventListener('keydown', mark, { capture: true });
    };
  }, []);

  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    if (!interacted.current) return;
    return focusMain();
  }, [pathname]);

  return null;
}
