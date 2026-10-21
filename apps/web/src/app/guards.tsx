import { useQueryClient } from '@tanstack/react-query';
import { lazy, useCallback } from 'react';
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router';

import { useConsentRefused } from '../auth/consentApi';
import { DEFAULT_SIGNED_IN_PATH, nextPath, signInPath } from '../auth/next';
import type { Me } from '../api/client';
import { useMe } from '../auth/useMe';
import { useLiveEvents, type LiveEvent } from '../events/useLiveEvents';
import { ClipNotices } from '../features/content/ClipNotices';
import { useClipNotices } from '../features/content/useClipNotices';
import { PENDING_KEYS, queryKeysForEvent } from './eventKeys';
import { ErrorPage } from './ErrorPage';
import { PageLoading } from './PageLoading';
import { RouteBoundary } from './RouteBoundary';

const ConsentPrompt = lazy(() => import('../auth/ConsentPrompt'));

/** Pages a learner who declines a new terms or privacy version still needs (ADR 0048). */
const OPEN_WHILE_CONSENT_OWED = new Set(['/settings', '/settings/delete-account']);

/**
 * Whether the consent prompt replaces the page (#104, ADR 0048). Settings stay open so
 * a learner who declines can export or delete their data. An open practice session is
 * not swapped out under the learner (it would void a Blind listen); it gets the prompt
 * once the server refuses one of its requests, or on the next page.
 */
function useConsentPromptShown(me: Me): boolean {
  const { pathname } = useLocation();
  const refused = useConsentRefused();
  if (me.consents_required.length === 0 || OPEN_WHILE_CONSENT_OWED.has(pathname)) return false;
  return refused || !pathname.startsWith('/sessions/');
}

/**
 * Pages below this route need a signed-in learner. Signed-out visitors go to sign
 * in and come back to the same address afterwards (the `next` parameter).
 */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();

  if (me.data) return <SignedInRoot key={me.data.id} me={me.data} />;
  if (me.isPending) return <PageLoading />;
  if (me.isError) return <ErrorPage error={me.error} onRetry={() => void me.refetch()} />;
  return <Navigate to={signInPath(location)} replace />;
}

/**
 * Everything a signed-in learner sees renders inside this component, so hooks that
 * need an account (for example the live-events connection) belong here.
 */
function SignedInRoot({ me }: { me: Me }) {
  const notices = useClipNotices();
  const consentPrompt = useConsentPromptShown(me);
  const queryClient = useQueryClient();
  const keysFor = useCallback(
    (event: LiveEvent) => queryKeysForEvent(event, queryClient),
    [queryClient],
  );
  useLiveEvents({
    keysFor,
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
        {/* A newer terms or privacy version is accepted before anything else (#104). */}
        {consentPrompt ? <ConsentPrompt required={me.consents_required} /> : <Outlet />}
      </RouteBoundary>
      <ClipNotices notices={notices} />
    </>
  );
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
