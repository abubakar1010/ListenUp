import { useId, useState } from 'react';

import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { useChangeEntry, type Session } from './api';
import { EntryChoice } from './EntryChoice';
import { entryFrom, entryIncludes } from './plan';
import { PlanPreview } from './PlanPreview';

/**
 * Change Blind, Dictation or both until Transcript starts (FR-PL-5, SR-3). A finished
 * entry exercise stays in the plan, so its box cannot be cleared. The new step count
 * shows before saving; after saving, the progress count updates and is announced.
 */
export function ChangeEntryPanel({ session, onClose }: { session: Session; onClose: () => void }) {
  const headingId = useId();
  const change = useChangeEntry(session);
  const [blind, setBlind] = useState(entryIncludes(session.entry, 'blind'));
  const [dictation, setDictation] = useState(entryIncludes(session.entry, 'dictation'));
  const entry = entryFrom(blind, dictation);

  const done = (step: 'blind' | 'dictation') =>
    session.steps.some((s) => s.step === step && s.status === 'done');
  const fixed = {
    ...(done('blind') ? { blind: 'done, kept' } : {}),
    ...(done('dictation') ? { dictation: 'done, kept' } : {}),
  };

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 rounded-md border border-line bg-surface-raised p-4 md:p-6"
    >
      <h2 id={headingId} className="font-display text-heading">
        Change how you start
      </h2>
      <EntryChoice
        idPrefix="change"
        blind={blind}
        dictation={dictation}
        fixed={fixed}
        onChange={(step, value) => (step === 'blind' ? setBlind(value) : setDictation(value))}
        error={entry ? undefined : 'Tick Blind, Dictation or both.'}
      />
      <div className="rounded-md bg-surface-sunken p-4">
        <PlanPreview entry={entry} lead="Your plan becomes" />
      </div>
      {change.isError && <ErrorPanel error={change.error} />}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" className={buttonClass('quiet')} onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className={buttonClass('primary')}
          disabled={!entry || entry === session.entry || session.entry_locked || change.isPending}
          onClick={() => entry && change.mutate(entry, { onSuccess: onClose })}
        >
          {change.isPending ? 'Saving…' : 'Save change'}
        </button>
      </div>
    </section>
  );
}
