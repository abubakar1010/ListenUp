import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router';

import { ME_KEY } from '../../auth/useMe';
import { buttonClass } from '../../components/button';
import { formatDeletionDate, GRACE_DAYS } from './deletionApi';

/**
 * Shown after the learner deletes their account (`/account-deleted?until=...`, #91).
 * It says when the data goes and how to get the account back (D9).
 */
export default function AccountDeletedPage() {
  const [searchParams] = useSearchParams();
  const until = searchParams.get('until');
  const queryClient = useQueryClient();

  useEffect(() => {
    // Nothing of the deleted account may stay cached; from here on nobody is signed in.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
    queryClient.setQueryData(ME_KEY, null);
  }, [queryClient]);

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
          <>Everything in it is kept for {GRACE_DAYS} days, then deleted for good.</>
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
