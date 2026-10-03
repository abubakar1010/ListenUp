import { ApiError } from '../api/client';

/** Turns a problem into the message shown to the learner (NFR-USE-3). */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return 'We could not reach ListenUp. Check your connection and try again.';
  }
  const lockedUntil = error.problem.locked_until;
  if (error.code === 'account_locked' && typeof lockedUntil === 'string') {
    const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'short' }).format(
      new Date(lockedUntil),
    );
    return `Too many failed sign-in attempts for this account. You can try again at ${time}.`;
  }
  return error.problem.detail;
}
