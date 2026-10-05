import { NavLink, Outlet } from 'react-router';

import { useMe } from '../auth/useMe';
import { AccountMenu } from './AccountMenu';
import { HEADER_CLASS } from './headerClass';
import { RouteBoundary } from './RouteBoundary';
import { Wordmark } from './Wordmark';

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center px-3 font-bold text-ink no-underline hover:text-ink ${
    isActive ? 'shadow-[inset_0_-3px_0_var(--color-accent)]' : 'rounded-md'
  }`;

/**
 * Library-type pages (UI-1): header with the wordmark, main navigation and the
 * account menu. Practice screens use PracticeLayout instead. Only rendered for a
 * signed-in learner (inside RequireAuth).
 */
export function AppLayout() {
  const me = useMe();
  return (
    <>
      <header className={HEADER_CLASS}>
        <Wordmark to="/library" />
        <nav aria-label="Main" className="md:ml-6">
          <ul className="flex items-center gap-1">
            <li>
              <NavLink to="/library" className={navLinkClass}>
                Library
              </NavLink>
            </li>
          </ul>
        </nav>
        <span className="flex-1" />
        {me.data && <AccountMenu me={me.data} />}
      </header>
      <RouteBoundary>
        <Outlet />
      </RouteBoundary>
    </>
  );
}
