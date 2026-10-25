import { useId, type ReactNode, type Ref } from 'react';

import { AlertIcon } from './icons';

/**
 * A rule the learner has met, not a mistake (UX-12, UX-17, UX-36): the daily limit of
 * new audio, an ended Blind attempt. Warning ink on the sunken ground, never the
 * danger red. `role` is "status" (polite) unless the log asks for an assertive
 * announcement (UX-22). Focusable from script, so a control that cannot act can point
 * here.
 */
export function CautionNotice({
  title,
  children,
  role = 'status',
  id,
  ref,
}: {
  title: string;
  children: ReactNode;
  role?: 'status' | 'alert';
  id?: string;
  ref?: Ref<HTMLDivElement>;
}) {
  const titleId = useId();
  return (
    <div
      ref={ref}
      id={id}
      role={role}
      aria-labelledby={titleId}
      tabIndex={-1}
      data-tone="caution"
      className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 rounded-md border-2 border-warning bg-surface-sunken p-4"
    >
      <span className="pt-0.5 text-warning">
        <AlertIcon className="size-6" />
      </span>
      <div className="flex flex-col gap-1">
        <h2 id={titleId} className="font-display text-heading break-words">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
