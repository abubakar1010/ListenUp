import { Link, useLocation } from 'react-router';

import { AuthForm } from './AuthForm';

const linkClass = 'text-blue-700 underline';

/** Keep `?next=...` when switching between sign-in and register, so the learner still
 * returns to the page that sent them here. */
function useKeepSearch(path: string): string {
  return path + useLocation().search;
}

export function SignInPage() {
  const registerPath = useKeepSearch('/register');
  return (
    <AuthForm
      mode="sign-in"
      footer={
        <>
          New to ListenUp?{' '}
          <Link to={registerPath} className={linkClass}>
            Create an account
          </Link>
          <br />
          <Link to="/forgot-password" className={linkClass}>
            Forgot your password?
          </Link>
        </>
      }
    />
  );
}

export function RegisterPage() {
  const signInPath = useKeepSearch('/sign-in');
  return (
    <AuthForm
      mode="register"
      footer={
        <>
          Already have an account?{' '}
          <Link to={signInPath} className={linkClass}>
            Sign in
          </Link>
        </>
      }
    />
  );
}
