import { Outlet } from 'react-router';

import { HEADER_CLASS } from './headerClass';
import { RouteBoundary } from './RouteBoundary';
import { Wordmark } from './Wordmark';

/** Pages for visitors who are not signed in: sign in, register, password reset, not found. */
export function PublicLayout() {
  return (
    <>
      <header className={HEADER_CLASS}>
        <Wordmark to="/" />
      </header>
      <RouteBoundary>
        <Outlet />
      </RouteBoundary>
    </>
  );
}
