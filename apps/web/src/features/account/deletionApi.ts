import { api } from '../../api/client';
import type { components } from '../../api/schema';

export type DeletionScheduled = components['schemas']['DeletionScheduled'];

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
