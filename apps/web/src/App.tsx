import { lazy } from 'react';
import { Route, Routes } from 'react-router';

import { AppLayout } from './app/AppLayout';
import { HomeRedirect, RedirectIfSignedIn, RequireAuth } from './app/guards';
import { PageTitle } from './app/PageTitle';
import { PublicLayout } from './app/PublicLayout';
import { RouteFocus } from './app/RouteFocus';
import { SkipLink } from './app/SkipLink';
import { RegisterPage, SignInPage } from './auth/pages';

// Route-based code splitting: each page below downloads when it is first opened.
// The sign-in and register pages stay in the first bundle, because signed-out
// visitors land on them.
const LibraryPage = lazy(() => import('./features/library/LibraryPage'));
const SessionPage = lazy(() => import('./features/session/SessionPage'));
const NotFoundPage = lazy(() => import('./app/NotFoundPage'));
const PasswordResetRequestPage = lazy(() =>
  import('./auth/PasswordResetPages').then((m) => ({ default: m.PasswordResetRequestPage })),
);
const PasswordResetConfirmPage = lazy(() =>
  import('./auth/PasswordResetPages').then((m) => ({ default: m.PasswordResetConfirmPage })),
);

export function App() {
  return (
    <>
      <SkipLink />
      <RouteFocus />
      <Routes>
        <Route path="/" element={<HomeRedirect />} />

        <Route element={<PublicLayout />}>
          <Route element={<RedirectIfSignedIn />}>
            <Route
              path="/sign-in"
              element={
                <>
                  <PageTitle title="Sign in" />
                  <SignInPage />
                </>
              }
            />
            <Route
              path="/register"
              element={
                <>
                  <PageTitle title="Create account" />
                  <RegisterPage />
                </>
              }
            />
          </Route>
          {/* Outside RedirectIfSignedIn: a reset link must also work while signed in. */}
          <Route
            path="/forgot-password"
            element={
              <>
                <PageTitle title="Reset your password" />
                <PasswordResetRequestPage />
              </>
            }
          />
          <Route
            path="/reset-password"
            element={
              <>
                <PageTitle title="Choose a new password" />
                <PasswordResetConfirmPage />
              </>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/library" element={<LibraryPage />} />
          </Route>
          <Route path="/sessions/:sessionId" element={<SessionPage />} />
        </Route>
      </Routes>
    </>
  );
}
