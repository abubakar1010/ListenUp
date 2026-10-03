/**
 * Moves keyboard focus to the page's <main>, so after a skip link or a page change
 * the next Tab starts in the content and screen readers read the new page.
 * Waits briefly for <main> when the page's code is still loading.
 */
export function focusMain(timeoutMs = 3000): () => void {
  const tryFocus = (): boolean => {
    const main = document.querySelector<HTMLElement>('main');
    if (!main) return false;
    if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
    main.focus({ preventScroll: false });
    return true;
  };
  if (tryFocus()) return () => {};

  const observer = new MutationObserver(() => {
    if (tryFocus()) stop();
  });
  const timer = window.setTimeout(() => stop(), timeoutMs);
  function stop() {
    observer.disconnect();
    window.clearTimeout(timer);
  }
  observer.observe(document.body, { childList: true, subtree: true });
  return stop;
}
