import { useEffect } from 'react';

/** Sets the browser tab title for the current page, for example "Library · ListenUp". */
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · ListenUp`;
  }, [title]);
}
