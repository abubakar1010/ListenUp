import { useMutation } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';

import { ApiError } from '../../api/client';
import { buttonClass } from '../../components/button';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useMe } from '../../auth/useMe';
import { deleteAccount } from './deletionApi';

const inputClass =
  'min-h-11 rounded-md border border-line-strong bg-surface-raised px-3 py-2 focus:outline-2 focus:outline-offset-2 focus:outline-focus-ring aria-invalid:border-danger';

/** Codes shown next to the password field instead of in the dialog. */
const FIELD_CODES = new Set(['wrong_password', 'account_locked']);

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

/**
 * "Delete your account" (FR-ACC-4, #91; ADR 0029): the learner enters their password,
 * confirms in a dialog, and is signed out with the date until which they can restore
 * the account by signing in (D9). Self-contained, so it can sit on any settings page.
 */
export function DeleteAccountSection() {
  const navigate = useNavigate();
  // The server decides the grace period (LISTENUP_ACCOUNT_DELETION_GRACE_DAYS).
  const graceDays = useMe().data?.deletion_grace_days;
  const grace =
    graceDays === undefined ? 'a few days' : `${graceDays} ${graceDays === 1 ? 'day' : 'days'}`;
  const ids = { password: useId(), error: useId(), heading: useId(), explain: useId() };
  const passwordRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  // Bumped to move focus to the password field once the dialog has closed.
  const [focusRequest, setFocusRequest] = useState(0);

  useEffect(() => {
    if (focusRequest === 0) return;
    // Runs after the dialog's own cleanup has queued focus back to its opener, so
    // this later timer wins and the learner lands on the field to fix.
    const timer = window.setTimeout(() => passwordRef.current?.focus());
    return () => window.clearTimeout(timer);
  }, [focusRequest]);

  const remove = useMutation({
    mutationFn: () => deleteAccount(password),
    onSuccess: (result) => {
      // The next page forgets the learner; doing it here would make the signed-in
      // guard send this page to sign in first.
      void navigate(`/account-deleted?until=${encodeURIComponent(result.deletion_scheduled_at)}`, {
        replace: true,
      });
    },
    onError: (error) => {
      if (error instanceof ApiError && FIELD_CODES.has(error.code)) {
        setConfirming(false);
        setFieldError(fieldMessage(error));
        setFocusRequest((count) => count + 1);
      }
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!password) {
      setFieldError('Enter your password to delete your account.');
      passwordRef.current?.focus();
      return;
    }
    setFieldError(null);
    remove.reset();
    setConfirming(true);
  }

  const dialogError =
    remove.isError && !(remove.error instanceof ApiError && FIELD_CODES.has(remove.error.code))
      ? remove.error
      : null;

  return (
    <section
      aria-labelledby={ids.heading}
      className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 id={ids.heading} className="font-display text-heading-compact md:text-heading">
        Delete your account
      </h2>
      <div id={ids.explain} className="flex flex-col gap-2">
        <p>
          Deleting your account signs you out on every device at once, and nobody can use the
          account after that.
        </p>
        <p>
          Your library, practice sessions, cards and recordings are kept for {grace}. If you change
          your mind, sign in within that time and restore the account. After that, everything is
          deleted for good.
        </p>
      </div>
      <form
        className="flex flex-col gap-3"
        onSubmit={onSubmit}
        noValidate
        aria-describedby={ids.explain}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.password} className="font-bold">
            Your password
          </label>
          <input
            ref={passwordRef}
            id={ids.password}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setFieldError(null);
            }}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={ids.error}
            className={`${inputClass} max-w-sm`}
          />
        </div>
        <p id={ids.error} role="alert" className="min-h-6 text-danger">
          {fieldError}
        </p>
        <div>
          <button type="submit" className={buttonClass('secondary', 'text-danger')}>
            Delete my account
          </button>
        </div>
      </form>

      {confirming && (
        <ConfirmDialog
          title="Delete your account?"
          confirmLabel="Delete my account"
          cancelLabel="Keep my account"
          busy={remove.isPending}
          busyLabel="Deleting…"
          onConfirm={() => remove.mutate()}
          onCancel={() => {
            setConfirming(false);
            remove.reset();
          }}
          footer={dialogError ? <ErrorPanel error={dialogError} /> : undefined}
        >
          <p>
            You will be signed out at once. Everything in your account is deleted after {grace},
            unless you sign in before then and restore it.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
