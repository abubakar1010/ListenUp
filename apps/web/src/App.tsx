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
const GoogleErrorPage = lazy(() => import('./auth/GoogleErrorPage'));
const DeckPage = lazy(() => import('./features/cards/DeckPage'));
const MarksPage = lazy(() => import('./features/review/MarksPage'));
const LibraryPage = lazy(() => import('./features/library/LibraryPage'));
const AddClipPage = lazy(() => import('./features/library/AddClipPage'));
const ContentPage = lazy(() => import('./features/content/ContentPage'));
const SessionPage = lazy(() => import('./features/session/SessionPage'));
const StartPlanPage = lazy(() => import('./features/session/StartPlanPage'));
const SettingsPage = lazy(() => import('./features/account/SettingsPage'));
const DeleteAccountPage = lazy(() => import('./features/account/DeleteAccountPage'));
const JobsPage = lazy(() => import('./features/admin/JobsPage'));
const UsagePage = lazy(() => import('./features/admin/UsagePage'));
const LegalPage = lazy(() => import('./features/legal/LegalPage'));
const AccessibilityStatementPage = lazy(
  () => import('./features/legal/AccessibilityStatementPage'),
);
const NotFoundPage = lazy(() => import('./app/NotFoundPage'));
const AccountDeletedPage = lazy(() => import('./features/account/AccountDeletedPage'));
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
          <Route path="/auth/google-error" element={<GoogleErrorPage />} />
          {/* The current version of each legal text (#103, ADR 0051). */}
          <Route path="/terms" element={<LegalPage document="terms" />} />
          <Route path="/privacy" element={<LegalPage document="privacy" />} />
          <Route path="/voice-consent" element={<LegalPage document="voice_recording" />} />
          {/* #98: public, so it can be read before an account exists. */}
          <Route path="/accessibility" element={<AccessibilityStatementPage />} />
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
          <Route
            path="/account-deleted"
            element={
              <>
                <PageTitle title="Account deleted" />
                <AccountDeletedPage />
              </>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/cards" element={<DeckPage />} />
            <Route path="/marks" element={<MarksPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/library/add" element={<AddClipPage />} />
            <Route path="/contents/:contentId" element={<ContentPage />} />
            <Route path="/contents/:contentId/plan" element={<StartPlanPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/settings/delete-account" element={<DeleteAccountPage />} />
            <Route path="/admin/jobs" element={<JobsPage />} />
            <Route path="/admin/usage" element={<UsagePage />} />
          </Route>
          <Route path="/sessions/:sessionId" element={<SessionPage />} />
        </Route>
      </Routes>
    </>
  );
}
