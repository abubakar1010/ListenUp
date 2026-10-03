import type { ReactNode } from 'react';
import { useParams } from 'react-router';

import { usePageTitle } from '../../app/usePageTitle';
import { PracticeLayout } from './PracticeLayout';

/** Marks an empty slot until the story that fills it lands. */
function Slot({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex min-h-16 flex-col justify-center gap-1 rounded-md border-2 border-dashed border-line-strong bg-surface-raised p-4">
      <p className="text-label text-ink-muted uppercase">{name}</p>
      <p className="text-body-s text-ink-muted">{children}</p>
    </div>
  );
}

/**
 * A practice session (`/sessions/:sessionId`). For now it shows the practice screen
 * skeleton; each mode story fills the slots from the session's plan.
 */
export default function SessionPage() {
  const { sessionId } = useParams();
  usePageTitle('Practice');

  return (
    <PracticeLayout
      heading="Practice session"
      clipTitle="Practice session"
      clipMeta={sessionId}
      back={{ to: '/library', label: 'Library' }}
      progress={<Slot name="Plan progress">Your plan's steps will show here.</Slot>}
      player={<Slot name="Player">The clip's player will show here.</Slot>}
      rule="Each step shows its one rule here."
      aside={<Slot name="Side panel">Marks and feedback will show here.</Slot>}
    >
      <Slot name="Work area">The work for the current step will show here.</Slot>
    </PracticeLayout>
  );
}
