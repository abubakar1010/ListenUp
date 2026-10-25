import { useState, type ReactNode } from 'react';

import { buttonClass } from '../../components/button';

import { CheckIcon, LockIcon } from '../../components/icons';
import { Sheet } from '../../components/Sheet';
import { progressText, type Session } from './api';
import { STEP_NAMES } from './plan';

type StepState = Session['steps'][number];

/*
 * Bars differ by fill as well as hue (UX-09, WCAG 1.4.1): done is a soft fill with an
 * outline, the open step is solid, skipped is a thin outline only, locked is empty.
 */
const BAR: Record<StepState['status'], { fill: string; className: string }> = {
  done: { fill: 'soft', className: 'bg-accent-soft ring-1 ring-inset ring-accent' },
  skipped: { fill: 'outline', className: 'ring-1 ring-inset ring-line-strong' },
  open: { fill: 'solid', className: 'bg-accent' },
  locked: { fill: 'empty', className: 'bg-line' },
};

const STATUS_LABELS: Record<StepState['status'], string> = {
  done: 'Done',
  skipped: 'Skipped',
  open: 'Now',
  locked: 'Locked',
};

/**
 * The plan's progress (UI-1): "Step N of M", then every step in order with its state.
 * An ordered list; the open step has aria-current="step". The count is a polite live
 * region, so a change of entry is announced ("Step 1 of 5"). Below 640 px the step
 * names do not fit, so a Plan button opens a sheet with the full list (UX-09); Blind
 * playback passes `plan={false}` (UX-19).
 */
export function StepProgress({
  session,
  actions,
  plan = true,
}: {
  session: Session;
  actions?: ReactNode;
  plan?: boolean;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
        <p aria-live="polite" className="font-bold" data-testid="progress-count">
          {progressText(session)}
          {session.open_step && (
            <span className="font-normal text-ink-muted"> · {STEP_NAMES[session.open_step]}</span>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {plan && (
            <button
              type="button"
              aria-haspopup="dialog"
              className={buttonClass('quiet', 'sm:hidden')}
              onClick={() => setSheetOpen(true)}
            >
              Plan
            </button>
          )}
          {actions}
        </div>
      </div>
      <ol aria-label="Plan steps" className="grid auto-cols-fr grid-flow-col gap-1 sm:gap-2">
        {session.steps.map((state) => (
          <StepItem key={state.step} state={state} />
        ))}
      </ol>
      {sheetOpen && (
        <Sheet title="Your plan" onClose={() => setSheetOpen(false)}>
          <PlanList session={session} />
        </Sheet>
      )}
    </div>
  );
}

function PlanList({ session }: { session: Session }) {
  return (
    <ol className="flex flex-col gap-2">
      {session.steps.map((state) => {
        const open = state.status === 'open';
        return (
          <li
            key={state.step}
            aria-current={open ? 'step' : undefined}
            className={`flex min-h-11 items-center gap-3 rounded-md px-3 ${
              open ? 'bg-accent-soft font-bold' : ''
            }`}
          >
            <span className={state.status === 'skipped' ? 'line-through' : ''}>
              {state.position}. {STEP_NAMES[state.step]}
            </span>{' '}
            <span className="ml-auto inline-flex items-center gap-1 text-body-s">
              {state.status === 'done' && <CheckIcon className="size-4 text-success" />}
              {state.status === 'locked' && <LockIcon className="size-3.5" />}
              {open ? (
                <span className="rounded-full bg-accent px-2 text-label text-on-accent">Now</span>
              ) : (
                <span className="text-ink-muted">{STATUS_LABELS[state.status]}</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StepItem({ state }: { state: StepState }) {
  const name = STEP_NAMES[state.step];
  const open = state.status === 'open';
  return (
    <li
      aria-current={open ? 'step' : undefined}
      className="flex min-w-0 flex-col gap-1"
      data-status={state.status}
    >
      <span
        aria-hidden="true"
        data-bar={BAR[state.status].fill}
        className={`h-1.5 rounded-full ${BAR[state.status].className}`}
      />
      <span
        className={`sr-only min-w-0 flex-wrap items-center gap-1 text-body-s sm:not-sr-only sm:flex ${
          open ? 'font-bold text-ink' : 'text-ink-muted'
        }`}
      >
        {state.status === 'done' && <CheckIcon className="size-4 flex-none text-success" />}
        {state.status === 'locked' && <LockIcon className="size-3.5 flex-none" />}
        <span className={`truncate ${state.status === 'skipped' ? 'line-through' : ''}`}>
          {name}
        </span>
        <span className="sr-only">{STATUS_WORDS[state.status]}</span>
        {state.status === 'skipped' && <span aria-hidden="true">Skipped</span>}
        {open && (
          <span
            aria-hidden="true"
            className="rounded-full bg-accent px-2 text-label text-on-accent"
          >
            Now
          </span>
        )}
      </span>
    </li>
  );
}

const STATUS_WORDS: Record<StepState['status'], string> = {
  done: ', done',
  skipped: ', skipped',
  open: ', now',
  locked: ', locked',
};
