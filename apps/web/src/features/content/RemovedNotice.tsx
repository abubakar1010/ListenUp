import { Link } from 'react-router';

import { buttonClass } from '../../components/button';
import { AlertIcon } from '../../components/icons';
import type { ContentDetail } from './useContent';

/**
 * A takedown removed the clip (#105, NFR-USE-3): say so and why in plain words, and lead
 * to the practice the learner keeps. Shown on the clip's page and in place of a practice
 * step, since nothing can be played or added again.
 */
export function RemovedNotice({ item }: { item: ContentDetail }) {
  return (
    <div
      role="alert"
      className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 rounded-md border-2 border-warning bg-surface-raised p-4"
    >
      <span className="pt-0.5 text-warning">
        <AlertIcon className="size-6" />
      </span>
      <div className="flex flex-col items-start gap-2">
        <p className="font-bold">This clip was removed</p>
        <p>
          {item.removal?.message ??
            'We removed this clip after a rights complaint. Your sessions, marks and cards are kept.'}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Link to="/marks" className={buttonClass('secondary')}>
            Your marks
          </Link>
          <Link to="/cards" className={buttonClass('secondary')}>
            Your cards
          </Link>
        </div>
      </div>
    </div>
  );
}
