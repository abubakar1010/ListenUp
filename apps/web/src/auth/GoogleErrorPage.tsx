import { Link, useSearchParams } from 'react-router';

import { usePageTitle } from '../app/usePageTitle';
import { buttonClass } from '../components/button';

/** Full-page OIDC refusals land here with fixed, non-sensitive reason codes. */
export default function GoogleErrorPage() {
  usePageTitle('Google confirmation was not completed');
  const [params] = useSearchParams();
  const reauth = params.get('intent') === 'reauth';
  const fresh = reauth && params.get('reason') === 'fresh_auth';
  // A new Google account needs the current terms and privacy accepted first (#104).
  if (!reauth && params.get('reason') === 'consent') {
    return (
      <main className="mx-auto flex max-w-reading flex-col gap-5 p-6">
        <h1 className="font-display text-title-compact">Google confirmation was not completed</h1>
        <p role="alert">
          To create an account with Google, first accept the Terms of Service and Privacy Policy on
          the Create account page. No account was created.
        </p>
        <Link to="/register" className={buttonClass('primary')}>
          Create an account
        </Link>
        <Link to="/sign-in" className="font-bold text-accent">
          Back to sign in
        </Link>
      </main>
    );
  }
  return (
    <main className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <h1 className="font-display text-title-compact">Google confirmation was not completed</h1>
      <p role="alert">
        {fresh ? 'Google did not confirm a new sign-in. ' : 'The confirmation failed or expired. '}
        Your account has not been deleted by this confirmation.
      </p>
      {fresh && (
        <p>
          Sign out of your Google Account in another tab. Keep ListenUp open, return here and choose
          Continue with Google to sign in to Google again. Selecting an account or approving consent
          alone does not confirm a new sign-in.
        </p>
      )}
      <a
        className={buttonClass('primary')}
        href={
          reauth
            ? '/api/v1/auth/oidc/google/start?purpose=reauth'
            : '/api/v1/auth/oidc/google/start'
        }
      >
        Continue with Google
      </a>
      <Link to={reauth ? '/settings/delete-account' : '/sign-in'} className="font-bold text-accent">
        {reauth ? 'Back to account deletion' : 'Back to sign in'}
      </Link>
    </main>
  );
}
