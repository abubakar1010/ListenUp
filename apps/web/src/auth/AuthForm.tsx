import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import { api, ApiError, type Me } from '../api/client';
import { errorMessage } from './errorMessage';
import { ME_KEY } from './useMe';

type Mode = 'sign-in' | 'register';

const COPY = {
  'sign-in': { title: 'Sign in', submit: 'Sign in', path: '/auth/login' },
  register: { title: 'Create your account', submit: 'Create account', path: '/auth/register' },
} as const;

export function AuthForm({ mode, footer }: { mode: Mode; footer: ReactNode }) {
  const copy = COPY[mode];
  const ids = { email: useId(), password: useId(), error: useId(), hint: useId() };
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const submit = useMutation({
    mutationFn: () => api<Me>(copy.path, { method: 'POST', body: { email, password } }),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me);
      void navigate('/');
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit.mutate();
  }

  const error = submit.isError ? errorMessage(submit.error) : null;

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
        <button
          type="submit"
          disabled={submit.isPending}
          className="rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700 disabled:opacity-60"
        >
          {submit.isPending ? 'Please wait…' : copy.submit}
        </button>
      </form>
      <p className="mt-6">{footer}</p>
    </main>
  );
}
