import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { api, ApiError, type Me } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { formatDeletionDate } from '../features/account/api';
import { errorMessage } from './errorMessage';
import { nextPath } from './next';
import { ME_KEY } from './useMe';

type Mode = 'sign-in' | 'register';

/** The account is waiting for deletion: sign-in asks before restoring it (#120, D9). */
const PENDING_DELETION = 'account_pending_deletion';

function scheduledDate(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== PENDING_DELETION) return null;
  const at = error.problem.deletion_scheduled_at;
  return typeof at === 'string' ? at : null;
}

const COPY = {
  'sign-in': { title: 'Sign in', submit: 'Sign in', path: '/auth/login' },
  register: { title: 'Create your account', submit: 'Create account', path: '/auth/register' },
} as const;

export function AuthForm({ mode, footer }: { mode: Mode; footer: ReactNode }) {
  const copy = COPY[mode];
  const ids = { email: useId(), password: useId(), error: useId(), hint: useId() };
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  // While the restore question is open: the date the deleted account's data goes.
  const [restoreUntil, setRestoreUntil] = useState<string | null>(null);
  // Set when the learner chose to keep a deleted account deleted: the same date.
  const [keptDeleted, setKeptDeleted] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const submit = useMutation({
    mutationFn: (restore: boolean) =>
      api<Me>(copy.path, {
        method: 'POST',
        body: restore ? { email, password, restore: true } : { email, password },
      }),
    onError: (failure, restore) => {
      const at = scheduledDate(failure);
      if (at) setRestoreUntil(at);
      // A refused restore (the grace period just ended) closes the question; a
      // network failure keeps it open so the learner can try again.
      else if (!restore || failure instanceof ApiError) setRestoreUntil(null);
    },
    onSuccess: (me) => {
      setRestoreUntil(null);
      queryClient.setQueryData(ME_KEY, me);
      // Back to the page that sent the learner here, else the library.
      void navigate(nextPath(searchParams), { replace: true });
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setKeptDeleted(null);
    submit.mutate(false);
  }

  const failed = submit.isError && !scheduledDate(submit.error);
  const error = failed && !restoreUntil ? errorMessage(submit.error) : null;

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
        <p id={ids.error} role="alert" className="min-h-6 text-red-800">
          {error}
        </p>
        {keptDeleted && (
          <p role="status">
            Your account stays deleted, and you are not signed in. Everything in it will be deleted
            on {formatDeletionDate(keptDeleted)}.
          </p>
        )}
        <button
          type="submit"
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
