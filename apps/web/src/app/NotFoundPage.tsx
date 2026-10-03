import { Link } from 'react-router';

import { buttonClass } from '../components/button';
import { usePageTitle } from './usePageTitle';

export default function NotFoundPage() {
  usePageTitle('Page not found');
  return (
    <main className="mx-auto flex w-full max-w-content flex-col items-start gap-4 px-4 py-8 md:px-6 md:py-12 xl:px-8">
      <h1 className="font-display text-title-compact md:text-title">Page not found</h1>
      <p>There is no page at this address. The link may be old or mistyped.</p>
      <Link to="/" className={buttonClass('primary')}>
        Go to your library
      </Link>
    </main>
  );
}
