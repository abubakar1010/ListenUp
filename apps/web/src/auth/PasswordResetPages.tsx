import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'react-router';

import { api, ApiError } from '../api/client';
import type { components } from '../api/schema';
import { errorMessage } from './errorMessage';
import { ME_KEY } from './useMe';

type ResetRequested = components['schemas']['PasswordResetRequested'];

const inputClass =
  'rounded border border-gray-400 px-3 py-2 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700';
const buttonClass =
  'rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700 disabled:opacity-60';
const linkClass = 'text-blue-700 underline';

/** Asks for a reset email (FR-ACC-3). Route: /forgot-password. */
export function PasswordResetRequestPage() {
  const ids = { email: useId(), error: useId() };
  const [email, setEmail] = useState('');

  const submit = useMutation({
    mutationFn: () =>
      api<ResetRequested>('/auth/password-reset', { method: 'POST', body: { email } }),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit.mutate();
  }

  const error = submit.isError ? errorMessage(submit.error) : null;

  return (
    <main className="mx-auto max-w-sm p-6">
      <h1 className="text-2xl font-semibold">Reset your password</h1>
      {submit.isSuccess ? (
        // role="status" announces the outcome without moving focus.
        <p role="status" className="mt-6">
          {submit.data.detail}
        </p>
      ) : (
        <form
          className="mt-6 flex flex-col gap-4"
          onSubmit={onSubmit}
          noValidate
          aria-describedby={error ? ids.error : undefined}
        >
          <p>
            Enter the email you signed up with. We will send you a link to choose a new password.
          </p>
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
              aria-invalid={
                submit.error instanceof ApiError && submit.error.code === 'invalid_email'
              }
              className={inputClass}
            />
          </div>
          <p id={ids.error} role="alert" className="min-h-6 text-red-800">
            {error}
          </p>
          <button type="submit" disabled={submit.isPending} className={buttonClass}>
            {submit.isPending ? 'Please wait…' : 'Send reset link'}
          </button>
        </form>
      )}
      <p className="mt-6">
        <Link to="/sign-in" className={linkClass}>
          Back to sign in
        </Link>
      </p>
    </main>
  );
}

/** The token from a link like /reset-password#token=…; the fragment never reaches a server. */
function tokenFromHash(hash: string): string | null {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token') || null;
}

/** Sets a new password with the emailed token (FR-ACC-3). Route: /reset-password. */
export function PasswordResetConfirmPage() {
  const ids = { password: useId(), hint: useId(), error: useId() };
  const token = tokenFromHash(useLocation().hash);
  const [password, setPassword] = useState('');
  const queryClient = useQueryClient();

  const submit = useMutation({
    mutationFn: () =>
      api<void>('/auth/password-reset/confirm', { method: 'POST', body: { token, password } }),
    // A reset signs the learner out everywhere, this browser included.
    onSuccess: () => queryClient.setQueryData(ME_KEY, null),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit.mutate();
  }

  const linkDead = submit.error instanceof ApiError && submit.error.code === 'invalid_reset_link';
  const error = submit.isError ? errorMessage(submit.error) : null;

  let body;
  if (!token) {
    body = (
      <p role="alert" className="mt-6">
        This reset link is incomplete. Open the link from the email again, or{' '}
        <Link to="/forgot-password" className={linkClass}>
          ask for a new link
        </Link>
        .
      </p>
    );
  } else if (submit.isSuccess) {
    body = (
      <p role="status" className="mt-6">
        Your password has been changed and you have been signed out everywhere.{' '}
        <Link to="/sign-in" className={linkClass}>
          Sign in with your new password
        </Link>
        .
      </p>
    );
  } else {
    body = (
      <form
        className="mt-6 flex flex-col gap-4"
        onSubmit={onSubmit}
        noValidate
        aria-describedby={error ? ids.error : undefined}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.password} className="font-medium">
            New password
          </label>
          <input
            id={ids.password}
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby={ids.hint}
            aria-invalid={submit.error instanceof ApiError && submit.error.code === 'weak_password'}
            className={inputClass}
          />
          <p id={ids.hint} className="text-sm text-gray-700">
            At least 8 characters.
          </p>
        </div>
        <div id={ids.error} role="alert" className="min-h-6 text-red-800">
          {error}
          {linkDead && (
            <>
              {' '}
              <Link to="/forgot-password" className={linkClass}>
                Ask for a new link
              </Link>
            </>
          )}
        </div>
        <button type="submit" disabled={submit.isPending} className={buttonClass}>
          {submit.isPending ? 'Please wait…' : 'Set new password'}
        </button>
      </form>
    );
  }

  return (
    <main className="mx-auto max-w-sm p-6">
      <h1 className="text-2xl font-semibold">Choose a new password</h1>
      {body}
    </main>
  );
}
