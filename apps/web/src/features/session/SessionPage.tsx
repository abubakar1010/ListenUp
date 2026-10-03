import { useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';

import { PageLoading } from '../../app/PageLoading';
import { usePageTitle } from '../../app/usePageTitle';
import { buttonClass } from '../../components/button';
import { ErrorPanel } from '../../components/ErrorPanel';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { BlindStep } from '../blind/BlindStep';
import { CheckIcon, LockIcon } from '../../components/icons';
import { DictationScreen } from '../dictation/DictationScreen';
import { useSession, useSkipStep, type Session } from './api';
import { ChangeEntryPanel } from './ChangeEntryPanel';
import { PracticeLayout } from './PracticeLayout';
import { STEP_DESCRIPTIONS, STEP_NAMES, STEP_RULES } from './plan';
import { StepProgress } from './StepProgress';
import { formatClock } from './time';

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
 * A practice session (`/sessions/:sessionId`): the plan's progress and the open step
 * (UI-1). Each mode story fills the player and the work area for its step.
 */
export default function SessionPage() {
  const { sessionId = '' } = useParams();
  const session = useSession(sessionId);
  usePageTitle(session.data?.open_step ? STEP_NAMES[session.data.open_step] : 'Practice');

  if (session.isPending) return <PageLoading />;
  if (session.isError) {
    return (
      <main className="mx-auto flex w-full max-w-content flex-col gap-4 px-4 pt-4 pb-8 md:px-6 md:pt-8">
        <h1 className="sr-only">Practice session</h1>
        <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />
      </main>
    );
  }
  return <SessionView session={session.data} />;
}

function SessionView({ session }: { session: Session }) {
  const open = session.open_step;
  if (open === 'blind')
    return <BlindStep session={session} progress={<Progress session={session} />} />;
  // The session opens at its current step (#50); each mode fills its own screen.
  if (open === 'dictation') {
    return <DictationScreen session={session} progress={<Progress session={session} />} />;
  }
  const passage = `Passage ${formatClock(session.passage.start_ms)} to ${formatClock(session.passage.end_ms)}`;
  return (
    <PracticeLayout
      heading={`${open ? STEP_NAMES[open] : 'Plan complete'}: ${session.content_title}`}
      clipTitle={session.content_title}
      clipMeta={passage}
      back={{ to: '/library', label: 'Library' }}
      progress={<Progress session={session} />}
      player={<Slot name="Player">The clip's player will show here.</Slot>}
      rule={open ? STEP_RULES[open] : 'Plan complete.'}
      workLabel={open ? STEP_NAMES[open] : 'Plan complete'}
    >
      {open ? <OpenStep session={session} /> : <Finished session={session} />}
    </PracticeLayout>
  );
}

/** The step progress, with "Change entry" until Transcript starts (FR-PL-5). */
function Progress({ session }: { session: Session }) {
  const [editing, setEditing] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const canChange = session.status === 'active' && !session.entry_locked;

  let action = null;
  if (canChange) {
    action = (
      <button
        ref={toggle}
        type="button"
        className={buttonClass('quiet')}
        aria-expanded={editing}
        onClick={() => setEditing((value) => !value)}
      >
        Change entry
      </button>
    );
  } else if (session.status === 'active') {
    action = (
      <span className="flex items-center gap-1 text-body-s text-ink-muted">
        <LockIcon className="size-4" />
        Entry locked
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <StepProgress session={session} actions={action} />
      {editing && (canChange || session.entry_locked) && (
        <ChangeEntryPanel
          session={session}
          onClose={() => {
            setEditing(false);
            toggle.current?.focus();
          }}
        />
      )}
    </div>
  );
}

const SKIP_COPY = {
  card: {
    title: 'Skip Card?',
    body: "Cards keep the sounds you missed so you can review them later. If you skip, you can't make cards for this session.",
    confirm: 'Skip Card',
    cancel: 'Make a card',
  },
  shadow: {
    title: 'Skip Shadow?',
    body: 'Shadow trains your rhythm on the part with your marks. If you skip, your plan ends here and is marked complete without Shadow.',
    confirm: 'Skip Shadow and finish',
    cancel: 'Do Shadow',
  },
} as const;

/** Skip Card or Shadow, behind a confirmation (FR-PL-7). Other steps have no skip. */
function SkipControl({ session, step }: { session: Session; step: 'card' | 'shadow' }) {
  const [confirming, setConfirming] = useState(false);
  const skip = useSkipStep(session);
  const copy = SKIP_COPY[step];
  return (
    <>
      <button
        type="button"
        className={buttonClass('secondary', 'self-start')}
        onClick={() => {
          skip.reset();
          setConfirming(true);
        }}
      >
        Skip {STEP_NAMES[step]}
      </button>
      {confirming && (
        <ConfirmDialog
          title={copy.title}
          confirmLabel={copy.confirm}
          cancelLabel={copy.cancel}
          busy={skip.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() => skip.mutate(step, { onSuccess: () => setConfirming(false) })}
          footer={skip.isError ? <ErrorPanel error={skip.error} /> : undefined}
        >
          <p>{copy.body}</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function OpenStep({ session }: { session: Session }) {
  const open = session.open_step!;
  return (
    <div className="flex flex-col gap-3 rounded-md border-2 border-accent bg-surface-raised p-4 md:p-6">
      <p className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-accent px-2 text-label text-on-accent">Now</span>
        <b className="font-display text-heading">
          {session.open_position} · {STEP_NAMES[open]}
        </b>
      </p>
      <p>{STEP_DESCRIPTIONS[open]}</p>
      <p className="text-body-s text-ink-muted">This step's exercise will open here.</p>
      {open === 'transcript' && (
        <p className="text-body-s">Transcript can't be skipped: it shows what you missed.</p>
      )}
      {(open === 'card' || open === 'shadow') && <SkipControl session={session} step={open} />}
    </div>
  );
}

function Finished({ session }: { session: Session }) {
  const skipped = session.steps
    .filter((s) => s.status === 'skipped')
    .map((s) => STEP_NAMES[s.step]);
  return (
    <div className="flex flex-col items-start gap-3 rounded-md border border-line bg-surface-raised p-4 md:p-6">
      <p className="flex items-center gap-2 font-display text-heading">
        <CheckIcon className="size-5 text-success" />
        {session.status === 'completed' ? 'Plan complete' : 'This plan has stopped'}
      </p>
      {skipped.length > 0 && <p>Skipped: {skipped.join(' and ')}.</p>}
      <Link to={`/contents/${session.content_id}/plan`} className={buttonClass('primary')}>
        Start another plan on this clip
      </Link>
    </div>
  );
}
