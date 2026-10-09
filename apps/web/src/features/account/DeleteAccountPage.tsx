import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';

import { ApiError } from '../../api/client';
import { usePageTitle } from '../../app/usePageTitle';
import { ME_KEY, useMe } from '../../auth/useMe';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import {
  DELETE_ACCOUNT_KEY,
  deleteAccount,
  deletionSummary,
  type DeletionSummary,
} from './deletionApi';

const PAGE_CLASS =
  'mx-auto flex w-full max-w-reading flex-col gap-6 px-4 pt-4 pb-8 md:gap-8 md:px-6 md:pt-8 md:pb-12';
const inputClass =
  'min-h-11 rounded-md border border-line-strong bg-surface-raised px-3 py-2 focus:outline-2 focus:outline-offset-2 focus:outline-focus-ring aria-invalid:border-danger';
const FIELD_CODES = new Set(['wrong_password', 'account_locked']);

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function deletionDay(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'full' }).format(date);
}

function fieldMessage(error: ApiError): string {
  const lockedUntil = error.problem.locked_until;
  if (error.code === 'account_locked' && typeof lockedUntil === 'string') {
    const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(
      new Date(lockedUntil),
    );
    return `Too many wrong passwords. You can try again at ${time}.`;
  }
  return error.problem.detail;
}

function WhatGoes({ summary }: { summary: DeletionSummary }) {
  return (
    <ul className="list-disc space-y-2 pl-6">
      <li>{plural(summary.clips, 'clip in your library', 'clips in your library')}</li>
      <li>{plural(summary.practice_sessions, 'practice session', 'practice sessions')}</li>
      <li>{plural(summary.cards, 'saved card', 'saved cards')}</li>
      <li>{plural(summary.recordings, 'recording', 'recordings')}</li>
      <li>Your profile, settings and practice results</li>
    </ul>
  );
}

/** The two-step account deletion page specified by UX-06 and UX-34. */
export default function DeleteAccountPage() {
  usePageTitle('Delete your account');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useMe();
  const graceDays = me.data?.deletion_grace_days ?? 7;
  const permanentDate = deletionDay(graceDays);
  const [step, setStep] = useState<1 | 2>(1);
  const [password, setPassword] = useState('');
  const [understood, setUnderstood] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const checkboxRef = useRef<HTMLInputElement>(null);
  const passwordId = useId();
  const passwordErrorId = useId();
  const checkboxId = useId();

  const summary = useQuery({
    queryKey: ['account', 'deletion-summary'],
    queryFn: deletionSummary,
    enabled: step === 1,
  });

  useEffect(() => {
    if (step === 2) passwordRef.current?.focus();
  }, [step]);

  const remove = useMutation({
    mutationKey: DELETE_ACCOUNT_KEY,
    mutationFn: () => deleteAccount(password),
    onSuccess: (result) => {
      void navigate(`/account-deleted?until=${encodeURIComponent(result.deletion_scheduled_at)}`, {
        replace: true,
      });
    },
    onError: (error) => {
      if (error instanceof ApiError && FIELD_CODES.has(error.code)) {
        setFieldError(fieldMessage(error));
        passwordRef.current?.focus();
      } else {
        // The server may have committed deletion even if its response was lost.
        void queryClient.invalidateQueries({ queryKey: ME_KEY });
      }
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    remove.reset();
    if (!password) {
      setFieldError('Enter your password to delete your account.');
      passwordRef.current?.focus();
      return;
    }
    if (!understood) {
      checkboxRef.current?.focus();
      return;
    }
    setFieldError(null);
    remove.mutate();
  }

  const requestError =
    remove.isError && !(remove.error instanceof ApiError && FIELD_CODES.has(remove.error.code))
      ? remove.error
      : null;

  return (
    <main className={PAGE_CLASS}>
      <div className="flex flex-col gap-2">
        <Link to="/settings" className="self-start font-bold text-accent">
          ← Back to settings
        </Link>
        <p className="text-body-s font-bold text-ink-muted">
          Step {step} of 2 · {step === 1 ? 'Check what will be deleted' : 'Confirm deletion'}
        </p>
        <h1 className="font-display text-title-compact md:text-title">Delete your account</h1>
      </div>

      {step === 1 ? (
        <section className="flex flex-col gap-5 rounded-md border border-line bg-surface-raised p-4 md:p-6">
          <div className="flex flex-col gap-2">
            <h2 className="font-display text-heading-compact md:text-heading">What will go</h2>
            <p>
              Your account will be switched off as soon as you confirm. It will be deleted for good
              on <strong>{permanentDate}</strong> unless you sign in before then and restore it.
            </p>
          </div>

          {summary.isPending ? (
            <p role="status">Counting your data…</p>
          ) : summary.isError ? (
            <ErrorPanel error={summary.error} onRetry={() => void summary.refetch()} />
          ) : (
            <WhatGoes summary={summary.data} />
          )}

          <div className="rounded-md bg-surface-sunken p-4">
            <p className="font-bold">Want a copy first?</p>
            <p>
              Go back and{' '}
              <Link to="/settings#data-export" className="font-bold text-accent">
                download your data
              </Link>{' '}
              before deleting your account.
            </p>
          </div>

          {summary.isSuccess && (
            <div>
              <button type="button" className={buttonClass('primary')} onClick={() => setStep(2)}>
                Continue
              </button>
            </div>
          )}
        </section>
      ) : (
        <form
          className="flex flex-col gap-5 rounded-md border border-line bg-surface-raised p-4 md:p-6"
          onSubmit={submit}
          noValidate
        >
          <div className="flex flex-col gap-2">
            <h2 className="font-display text-heading-compact md:text-heading">Confirm deletion</h2>
            <p>Re-enter your password and confirm that you understand what happens next.</p>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={passwordId} className="font-bold">
              Your password
            </label>
            <input
              ref={passwordRef}
              id={passwordId}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setFieldError(null);
              }}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby={passwordErrorId}
              className={`${inputClass} max-w-sm`}
            />
            <p id={passwordErrorId} role="alert" className="min-h-6 text-danger">
              {fieldError}
            </p>
          </div>

          <label htmlFor={checkboxId} className="flex min-h-11 items-start gap-3">
            <input
              ref={checkboxRef}
              id={checkboxId}
              type="checkbox"
              checked={understood}
              onChange={(event) => setUnderstood(event.target.checked)}
              className="mt-1 size-5 flex-none accent-accent"
            />
            <span>
              I understand this can't be undone. My account will be switched off now and deleted for
              good on <strong>{permanentDate}</strong>.
            </span>
          </label>

          {requestError && <ErrorPanel error={requestError} />}

          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              aria-disabled={remove.isPending}
              className={buttonClass('secondary', 'text-danger')}
            >
              {remove.isPending ? 'Deleting…' : 'Delete my account'}
            </button>
            <button
              type="button"
              className={buttonClass('quiet')}
              onClick={() => {
                remove.reset();
                setStep(1);
              }}
            >
              Back
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
