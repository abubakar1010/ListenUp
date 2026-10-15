import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type DeletionScheduled = components['schemas']['DeletionScheduled'];
export type DeletionSummary = components['schemas']['DeletionSummary'];

/**
 * The delete mutation. While it is in flight, this tab ignores its own `account.disabled`
 * event: the mutation goes to the "account deleted" page itself (see `guards.tsx`).
 */
export const DELETE_ACCOUNT_KEY = ['account', 'delete'] as const;

/** Counts for the review step of the account-deletion flow. */
export function deletionSummary(): Promise<DeletionSummary> {
  return api<DeletionSummary>('/me/deletion-summary');
}

/**
 * Delete the signed-in learner's account (FR-ACC-4, ADR 0029). The server asks for the
 * password again and disables the account at once; it is deleted for good after the
 * grace period unless the learner signs in and restores it.
 */
export function deleteAccount(password: string): Promise<DeletionScheduled> {
  return api<DeletionScheduled>('/me', { method: 'DELETE', body: { password, confirm: true } });
}

/** "Sunday 11 October 2026 at 20:30", in the learner's own time zone and locale. */
export function formatDeletionDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeStyle: 'short' }).format(date);
}
