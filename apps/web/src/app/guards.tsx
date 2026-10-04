import type { QueryKey } from '@tanstack/react-query';
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router';

import { DEFAULT_SIGNED_IN_PATH, nextPath, signInPath } from '../auth/next';
import { ME_KEY, useMe } from '../auth/useMe';
import { useLiveEvents, type LiveEvent } from '../events/useLiveEvents';
import { BLIND_KEY } from '../features/blind/api';
import { ClipNotices } from '../features/content/ClipNotices';
import { useClipNotices } from '../features/content/useClipNotices';
import { CONTENTS_KEY, contentKey } from '../features/content/useContent';
import { LIBRARY_KEY, UPLOAD_USAGE_KEY } from '../features/library/useLibrary';
import { ErrorPage } from './ErrorPage';
import { PageLoading } from './PageLoading';
import { RouteBoundary } from './RouteBoundary';

/**
 * Pages below this route need a signed-in learner. Signed-out visitors go to sign
 * in and come back to the same address afterwards (the `next` parameter).
 */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();

  if (me.data) return <SignedInRoot />;
  if (me.isPending) return <PageLoading />;
  if (me.isError) return <ErrorPage error={me.error} onRetry={() => void me.refetch()} />;
  return <Navigate to={signInPath(location)} replace />;
}

/**
 * Everything a signed-in learner sees renders inside this component, so hooks that
 * need an account (for example the live-events connection) belong here.
 */
function SignedInRoot() {
  const notices = useClipNotices();
  useLiveEvents({
    keysFor: queryKeysForEvent,
    // Clips still processing show in the library and on their own page; refetch both
    // when events may be missed.
    pendingKeys: PENDING_KEYS,
    // A clip that becomes ready while the learner is elsewhere in the app (#40).
    onEvent: notices.onEvent,
    // Not every environment has EventSource (jsdom in unit tests); the hook then stays off.
    enabled: typeof EventSource !== 'undefined',
  });
  return (
    <>
      <RouteBoundary>
        <Outlet />
      </RouteBoundary>
      <ClipNotices notices={notices} />
    </>
  );
}

const NO_KEYS: readonly QueryKey[] = [];
const PENDING_KEYS: readonly QueryKey[] = [LIBRARY_KEY, CONTENTS_KEY];

/**
 * Which cached queries each live event makes stale (ADR 0016). Feature stories add their
 * mappings here, for example `content.ready` to the content item and the library list.
 */
function queryKeysForEvent(event: LiveEvent): readonly QueryKey[] {
  switch (event.type) {
    case 'content.ready':
      // A converted clip also changes storage use and today's new audio.
      return [LIBRARY_KEY, contentKey(event.resourceId), UPLOAD_USAGE_KEY];
    case 'job.progress':
      return [LIBRARY_KEY, contentKey(event.resourceId)];
    case 'attempt.voided':
      // The event names the attempt only; refresh every Blind step shown (ADR 0024).
      return [BLIND_KEY];
    case 'account.disabled':
      // The account was deleted, perhaps in another tab (ADR 0029): refetching the
      // learner finds nobody signed in, and the guard goes to sign in.
      return [ME_KEY];
    default:
      return NO_KEYS;
  }
}

/** Sign-in and register: a learner who is already signed in goes on to `next`. */
export function RedirectIfSignedIn() {
  const me = useMe();
  const [searchParams] = useSearchParams();
  if (me.data) return <Navigate to={nextPath(searchParams)} replace />;
  return <Outlet />;
}

/** The site root has no page of its own: the library when signed in, else sign in. */
export function HomeRedirect() {
  const me = useMe();
  if (me.data) return <Navigate to={DEFAULT_SIGNED_IN_PATH} replace />;
  if (me.isPending) return <PageLoading />;
  if (me.isError) return <ErrorPage error={me.error} onRetry={() => void me.refetch()} />;
  return <Navigate to="/sign-in" replace />;
}
