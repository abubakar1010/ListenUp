import { Link } from 'react-router';

import { AuthForm } from './AuthForm';

const linkClass = 'text-blue-700 underline';

export function SignInPage() {
  return (
    <AuthForm
      mode="sign-in"
      footer={
        <>
          New to ListenUp?{' '}
          <Link to="/register" className={linkClass}>
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
  return (
    <AuthForm
      mode="register"
      footer={
        <>
          Already have an account?{' '}
          <Link to="/sign-in" className={linkClass}>
            Sign in
          </Link>
        </>
      }
    />
  );
}
