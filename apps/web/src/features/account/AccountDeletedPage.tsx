import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router';

import { api, ApiError, type Me } from '../../api/client';
import { ME_KEY } from '../../auth/useMe';
import { buttonClass } from '../../components/button';
import { formatDeletionDate } from './deletionApi';

type Check = 'checking' | 'deleted' | 'signed-in';

/**
 * Shown after the learner deletes their account (`/account-deleted?until=...`, #91).
 * It says when the data goes and how to get the account back (D9).
 *
 * The page asks the server first: a learner who restored the account and came back here
 * with the Back button is signed in, so nothing is cleared and they go to the library.
 */
export default function AccountDeletedPage() {
  const [searchParams] = useSearchParams();
  const until = searchParams.get('until');
  const queryClient = useQueryClient();
  const [check, setCheck] = useState<Check>('checking');

  useEffect(() => {
    let current = true;
    api<Me>('/me').then(
      () => current && setCheck('signed-in'),
      (error: unknown) => {
        if (!current) return;
        if (error instanceof ApiError && error.code === 'not_signed_in') {
          // Nothing of the deleted account may stay cached; nobody is signed in.
          queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
          queryClient.setQueryData(ME_KEY, null);
          setCheck('deleted');
        } else {
          // Could not tell (offline, server error): the account was deleted a moment
          // ago, so show the page without touching a session that may be valid.
          setCheck('deleted');
        }
      },
    );
    return () => {
      current = false;
    };
  }, [queryClient]);

  if (check === 'checking') return null;
  if (check === 'signed-in') return <Navigate to="/library" replace />;

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-4 p-6">
      <h1 className="font-display text-title-compact md:text-title">Your account is deleted</h1>
      <p>You are signed out on every device, and nobody can use the account now.</p>
      <p>
        {until ? (
          <>
            Everything in it is kept until <strong>{formatDeletionDate(until)}</strong>, then
            deleted for good.
          </>
        ) : (
          <>Everything in it is kept for a few days, then deleted for good.</>
        )}
      </p>
      <p>
        Changed your mind? Sign in with your email and password before then and choose{' '}
        <strong>Restore my account</strong>. Everything will be as you left it. We have also sent
        this to your email.
      </p>
      <div>
        <Link to="/sign-in" className={buttonClass('secondary')}>
          Go to sign in
        </Link>
      </div>
    </main>
  );
}
