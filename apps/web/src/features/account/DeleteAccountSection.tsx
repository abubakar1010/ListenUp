import { Link } from 'react-router';

import { useMe } from '../../auth/useMe';
import { buttonClass } from '../../components/button';

/** Entry point from Settings to the full, two-step deletion flow (UX-06). */
export function DeleteAccountSection() {
  const graceDays = useMe().data?.deletion_grace_days;
  const grace =
    graceDays === undefined ? 'a few days' : `${graceDays} ${graceDays === 1 ? 'day' : 'days'}`;

  return (
    <section className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6">
      <h2 className="font-display text-heading-compact md:text-heading">Delete your account</h2>
      <p>
        Review what will be deleted before you continue. Your account is switched off at once, but
        you can restore it by signing in during the {grace} before permanent deletion.
      </p>
      <div>
        <Link to="/settings/delete-account" className={buttonClass('secondary', 'text-danger')}>
          Review account deletion
        </Link>
      </div>
    </section>
  );
}
