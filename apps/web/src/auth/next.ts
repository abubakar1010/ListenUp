/** Where a signed-in learner goes when nothing else asks for a page. */
export const DEFAULT_SIGNED_IN_PATH = '/library';

/**
 * The page to return to after signing in, from the `next` search parameter.
 * Only paths on this site are allowed, so a crafted link cannot send the
 * learner to another site after they sign in.
 */
export function nextPath(search: URLSearchParams | string): string {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search;
  const next = params.get('next');
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) {
    return DEFAULT_SIGNED_IN_PATH;
  }
  return next;
}

/** The sign-in page, set to come back to `location` afterwards. */
export function signInPath(location: { pathname: string; search: string; hash: string }): string {
  const here = `${location.pathname}${location.search}${location.hash}`;
  if (here === '/' || location.pathname === '/sign-in') return '/sign-in';
  return `/sign-in?next=${encodeURIComponent(here)}`;
}
