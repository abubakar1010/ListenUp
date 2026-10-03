import { Link, useLocation } from 'react-router';

import { signInPath } from '../auth/next';
import { buttonClass } from './button';
import { describeError } from './describeError';
import { AlertIcon } from './icons';

interface ErrorPanelProps {
  error: unknown;
  /** Called by "Try again"; without it, "Try again" reloads the page. */
  onRetry?: () => void;
  /** 1 when the panel is the whole page, 2 (the default) inside a page. */
  headingLevel?: 1 | 2;
}

/**
 * Shows an error as what happened, the details, and what to do next, with one
 * action that does it (NFR-USE-3). Announced to screen readers when it appears.
 */
export function ErrorPanel({ error, onRetry, headingLevel = 2 }: ErrorPanelProps) {
  const view = describeError(error);
  const location = useLocation();
  const Heading = headingLevel === 1 ? 'h1' : 'h2';

  let action = null;
  if (view.action === 'retry' && onRetry) {
    action = (
      <button type="button" className={buttonClass('secondary')} onClick={onRetry}>
        Try again
      </button>
    );
  } else if (view.action === 'retry' || view.action === 'reload') {
    action = (
      <button
        type="button"
        className={buttonClass('secondary')}
        onClick={() => window.location.reload()}
      >
        Reload the page
      </button>
    );
  } else if (view.action === 'sign-in') {
    action = (
      <Link to={signInPath(location)} className={buttonClass('primary')}>
        Sign in
      </Link>
    );
  } else if (view.action === 'library') {
    action = (
      <Link to="/library" className={buttonClass('secondary')}>
        Go to your library
      </Link>
    );
  }

  return (
    <div
      role="alert"
      className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 rounded-md border-2 border-danger bg-surface-raised p-4"
    >
      <span className="pt-0.5 text-danger">
        <AlertIcon className="size-6" />
      </span>
      <div className="flex flex-col items-start gap-2">
        <Heading className="font-display text-heading">{view.title}</Heading>
        <p>{view.detail}</p>
        <p className="font-bold">{view.nextStep}</p>
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  );
}
