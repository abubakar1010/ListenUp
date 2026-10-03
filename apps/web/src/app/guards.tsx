import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router';

import { DEFAULT_SIGNED_IN_PATH, nextPath, signInPath } from '../auth/next';
import { useMe } from '../auth/useMe';
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
  return (
    <RouteBoundary>
      <Outlet />
    </RouteBoundary>
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
