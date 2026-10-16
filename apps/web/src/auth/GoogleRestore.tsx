import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { api, ApiError, type Me } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ErrorPanel } from '../components/ErrorPanel';
import { formatDeletionDate } from '../features/account/deletionApi';
import { nextPath } from './next';
import { changeSession } from './session';

/** The cookie proves Google authentication; only this explicit action restores. */
export function GoogleRestore() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [kept, setKept] = useState(false);
  const pending = useQuery({
    queryKey: ['google', 'restore'],
    queryFn: () =>
      api<{ deletion_scheduled_at: string; next_path: string }>('/auth/oidc/google/restore'),
    retry: false,
  });
  const restore = useMutation({
    meta: { changesSession: true },
    mutationFn: (restore: boolean) =>
      api<Me | undefined>('/auth/oidc/google/restore', { method: 'POST', body: { restore } }),
    onSuccess: (me) => {
      if (me) {
        changeSession(queryClient, me);
        void navigate(
          nextPath(new URLSearchParams({ next: pending.data?.next_path ?? '/library' })),
          { replace: true },
        );
      } else {
        changeSession(queryClient, null);
        setKept(true);
      }
    },
  });
  if (kept) return <p role="status">Your account stays deleted, and you are not signed in.</p>;
  if (pending.isPending) return <p role="status">Checking your account…</p>;
  if (pending.isError) return <ErrorPanel error={pending.error} />;
  if (restore.isError && restore.error instanceof ApiError && restore.error.problem.status < 500) {
    return <ErrorPanel error={restore.error} />;
  }
  return (
    <ConfirmDialog
      title="Restore your account?"
      confirmLabel="Restore my account"
      cancelLabel="Keep it deleted"
      busy={restore.isPending}
      onConfirm={() => restore.mutate(true)}
      onCancel={() => restore.mutate(false)}
      footer={restore.isError ? <ErrorPanel error={restore.error} /> : undefined}
    >
      <p>
        Your account will be deleted for good on{' '}
        {formatDeletionDate(pending.data.deletion_scheduled_at)}.
      </p>
      <p>Restore it to sign in and keep your library and practice data.</p>
    </ConfirmDialog>
  );
}
