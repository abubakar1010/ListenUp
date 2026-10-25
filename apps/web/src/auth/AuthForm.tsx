import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { api, ApiError, type Me } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { formatDeletionDate } from '../features/account/deletionApi';
import { ErrorPanel } from '../components/ErrorPanel';
import { CONSENT_VERSIONS_KEY, DOCUMENTS, useConsentVersions } from './consentApi';
import { errorMessage } from './errorMessage';
import { GoogleRestore } from './GoogleRestore';
import { nextPath } from './next';
import { changeSession } from './session';

type Mode = 'sign-in' | 'register';

/** The account is waiting for deletion: sign-in asks before restoring it (#120, D9). */
const PENDING_DELETION = 'account_pending_deletion';

function scheduledDate(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== PENDING_DELETION) return null;
  const at = error.problem.deletion_scheduled_at;
  return typeof at === 'string' ? at : null;
}

/** Sign-up needs the current terms and privacy versions (#104). */
const CONSENT_REQUIRED = 'Accept the Terms of Service and Privacy Policy to create an account.';

const COPY = {
  'sign-in': { title: 'Sign in', submit: 'Sign in', path: '/auth/login' },
  register: { title: 'Create your account', submit: 'Create account', path: '/auth/register' },
} as const;

export function AuthForm({ mode, footer }: { mode: Mode; footer: ReactNode }) {
  const copy = COPY[mode];
  const ids = {
    email: useId(),
    password: useId(),
    error: useId(),
    hint: useId(),
    consent: useId(),
    versions: useId(),
  };
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const registering = mode === 'register';
  const versions = useConsentVersions(registering);
  // The labels the learner ticked the box for: a newer version shown later is not
  // accepted until the box is ticked again.
  const shown = versions.data ? `${versions.data.terms}\n${versions.data.privacy}` : null;
  const [acceptedLabels, setAcceptedLabels] = useState<string | null>(null);
  const accepted = shown !== null && acceptedLabels === shown;
  const [consentError, setConsentError] = useState<string | null>(null);
  const consentBox = useRef<HTMLInputElement>(null);
  // While the restore question is open: the date the deleted account's data goes.
  const [restoreUntil, setRestoreUntil] = useState<string | null>(null);
  // Set when the learner chose to keep a deleted account deleted: the same date.
  const [keptDeleted, setKeptDeleted] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const submit = useMutation({
    meta: { changesSession: true },
    mutationFn: (restore: boolean) => {
      // The versions shown next to the box; the server refuses older ones (409).
      const consent = registering && versions.data;
      return api<Me>(copy.path, {
        method: 'POST',
        body: restore
          ? { email, password, restore: true }
          : consent
            ? { email, password, terms_version: consent.terms, privacy_version: consent.privacy }
            : { email, password },
      });
    },
    onError: (failure, restore) => {
      if (failure instanceof ApiError && failure.code === 'consent_version_changed') {
        // A newer version was published while the form was open: show it, ask again.
        setAcceptedLabels(null);
        void queryClient.invalidateQueries({ queryKey: CONSENT_VERSIONS_KEY });
      }
      const at = scheduledDate(failure);
      if (at) setRestoreUntil(at);
      // A refused restore (the grace period just ended) closes the question; a
      // network failure keeps it open so the learner can try again.
      else if (!restore || failure instanceof ApiError) setRestoreUntil(null);
    },
    onSuccess: (me) => {
      setRestoreUntil(null);
      changeSession(queryClient, me);
      // Back to the page that sent the learner here, else the library.
      void navigate(nextPath(searchParams), { replace: true });
    },
  });

  function requireConsent(): boolean {
    if (!registering || accepted) return true;
    submit.reset();
    setConsentError(CONSENT_REQUIRED);
    consentBox.current?.focus();
    return false;
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (paused) {
      // Sign in stays focusable while paused and points to the time (UX-10).
      errorRef.current?.focus();
      return;
    }
    setKeptDeleted(null);
    if (!requireConsent()) return;
    submit.mutate(false);
  }

  const next = encodeURIComponent(nextPath(searchParams));
  const googleStart =
    registering && versions.data
      ? `/api/v1/auth/oidc/google/start?next=${next}&terms_version=${encodeURIComponent(versions.data.terms)}&privacy_version=${encodeURIComponent(versions.data.privacy)}`
      : `/api/v1/auth/oidc/google/start?next=${next}`;
  const googleClass =
    'mt-4 inline-flex min-h-11 items-center rounded border px-4 py-2 font-bold focus:outline-2 focus:outline-offset-2';

  const failed = submit.isError && !scheduledDate(submit.error);
  const error = consentError ?? (failed && !restoreUntil ? errorMessage(submit.error) : null);
  // The sign-in lockout (D17, UX-35, ADR 0057): one warning before the pause, then the
  // time it ends with the minutes left, counted silently.
  const problem = submit.error instanceof ApiError ? submit.error : null;
  const lockedUntil =
    problem?.code === 'account_locked' && typeof problem.problem.locked_until === 'string'
      ? Date.parse(problem.problem.locked_until)
      : null;
  const now = useNow(lockedUntil !== null);
  const paused = lockedUntil !== null && now < lockedUntil;
  const minutesLeft = paused ? Math.ceil((lockedUntil - now) / 60_000) : 0;
  const oneTryLeft = problem?.code === 'invalid_credentials' && problem.problem.attempts_left === 1;
  const lockMinutes = problem?.problem.lock_minutes;
  const errorRef = useRef<HTMLParagraphElement>(null);
  const { reset } = submit;
  // When the pause ends, so does its message: the form is as before the first try.
  useEffect(() => {
    if (lockedUntil !== null && !paused) reset();
  }, [lockedUntil, paused, reset]);

  function keepDeleted() {
    // Nothing was signed in: declining only closes the question.
    setKeptDeleted(restoreUntil);
    setRestoreUntil(null);
    setPassword('');
    submit.reset();
  }

  return (
    <main className="mx-auto max-w-sm p-6">
      <h1 className="text-2xl font-semibold">{copy.title}</h1>
      {registering && (
        <div className="mt-4 flex items-start gap-2">
          <input
            ref={consentBox}
            id={ids.consent}
            type="checkbox"
            checked={accepted}
            // Nothing can be accepted before the learner can see which versions.
            disabled={shown === null}
            onChange={(event) => {
              setAcceptedLabels(event.target.checked ? shown : null);
              if (event.target.checked) setConsentError(null);
            }}
            aria-invalid={consentError !== null}
            aria-describedby={consentError ? `${ids.versions} ${ids.error}` : ids.versions}
            className="mt-1 size-5"
          />
          <label htmlFor={ids.consent}>
            I agree to the{' '}
            <Link to={DOCUMENTS.terms.path} target="_blank" className="text-blue-700 underline">
              {DOCUMENTS.terms.name}
            </Link>{' '}
            and the{' '}
            <Link to={DOCUMENTS.privacy.path} target="_blank" className="text-blue-700 underline">
              {DOCUMENTS.privacy.name}
            </Link>
            .
          </label>
        </div>
      )}
      {registering && (
        <div id={ids.versions} className="mt-2 text-sm text-gray-700">
          {versions.data ? (
            <p>
              {DOCUMENTS.terms.name} version {versions.data.terms}, {DOCUMENTS.privacy.name} version{' '}
              {versions.data.privacy}.
            </p>
          ) : versions.isError ? (
            <ErrorPanel error={versions.error} onRetry={() => void versions.refetch()} />
          ) : (
            <p role="status">Loading the current Terms of Service and Privacy Policy…</p>
          )}
        </div>
      )}
      {registering && !accepted ? (
        // A Google sign-up accepts the same documents, so it waits for the box, and
        // for the versions it would accept.
        <button
          type="button"
          className={`${googleClass} disabled:opacity-60`}
          onClick={requireConsent}
          disabled={!versions.data}
        >
          Continue with Google
        </button>
      ) : (
        <a className={googleClass} href={googleStart}>
          Continue with Google
        </a>
      )}
      {searchParams.get('google') === 'cancelled' && (
        <p role="status">Google sign-in was cancelled. You can try again.</p>
      )}
      {searchParams.get('google') === 'restore' && <GoogleRestore />}
      <form
        className="mt-6 flex flex-col gap-4"
        onSubmit={onSubmit}
        noValidate
        aria-describedby={error ? ids.error : undefined}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.email} className="font-medium">
            Email
          </label>
          <input
            id={ids.email}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={submit.error instanceof ApiError && submit.error.code === 'invalid_email'}
            className="rounded border border-gray-400 px-3 py-2 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.password} className="font-medium">
            Password
          </label>
          <input
            id={ids.password}
            type="password"
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            required
            minLength={mode === 'register' ? 8 : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby={mode === 'register' ? ids.hint : undefined}
            aria-invalid={submit.error instanceof ApiError && submit.error.code === 'weak_password'}
            className="rounded border border-gray-400 px-3 py-2 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700"
          />
          {mode === 'register' && (
            <p id={ids.hint} className="text-sm text-gray-700">
              At least 8 characters.
            </p>
          )}
        </div>
        {/* role="alert" makes screen readers announce the message, including the lockout time. */}
        <p
          id={ids.error}
          ref={errorRef}
          tabIndex={-1}
          role="alert"
          className="min-h-6 text-red-800"
        >
          {error}
          {oneTryLeft && (
            <span className="mt-1 block text-ink">
              {' '}
              One try left. After one more wrong try, sign-in pauses for{' '}
              {typeof lockMinutes === 'number' ? `${lockMinutes} minutes` : 'a while'}.
            </span>
          )}
        </p>
        {(paused || oneTryLeft) && (
          <p className="text-body-s">
            {paused && (
              <span>
                {minutesLeft} {minutesLeft === 1 ? 'minute' : 'minutes'} left.{' '}
              </span>
            )}
            <Link to="/forgot-password" className="text-blue-700 underline">
              Reset your password
            </Link>{' '}
            {paused ? 'to sign in now.' : 'if you are not sure of it.'}
          </p>
        )}
        {keptDeleted && (
          <p role="status">
            Your account stays deleted, and you are not signed in. Everything in it will be deleted
            on {formatDeletionDate(keptDeleted)}.
          </p>
        )}
        <button
          type="submit"
          aria-disabled={paused || undefined}
          aria-describedby={paused ? ids.error : undefined}
          disabled={submit.isPending}
          className="rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700 disabled:opacity-60"
        >
          {submit.isPending ? 'Please wait…' : copy.submit}
        </button>
      </form>
      <p className="mt-6">{footer}</p>
      {restoreUntil && (
        <ConfirmDialog
          title="Restore your account?"
          confirmLabel="Restore my account"
          cancelLabel="Keep it deleted"
          busy={submit.isPending}
          busyLabel="Restoring…"
          onConfirm={() => submit.mutate(true)}
          onCancel={keepDeleted}
          footer={
            failed ? (
              <p role="alert" className="text-danger">
                {errorMessage(submit.error)}
              </p>
            ) : undefined
          }
        >
          <p>
            You deleted this account. Everything in it will be deleted on{' '}
            <strong>{formatDeletionDate(restoreUntil)}</strong>.
          </p>
          <p className="mt-2">
            Restore it to sign in and find your library, sessions, cards and recordings as you left
            them.
          </p>
        </ConfirmDialog>
      )}
    </main>
  );
}

/** The time now, every second while `active` (for a countdown), else once. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [active]);
  return now;
}
