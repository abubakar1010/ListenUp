import type { ReactNode } from 'react';

import { CheckIcon, LockIcon } from '../../components/icons';
import { progressText, type Session } from './api';
import { STEP_NAMES } from './plan';

type StepState = Session['steps'][number];

const BAR: Record<StepState['status'], string> = {
  done: 'bg-success',
  skipped: 'bg-line-strong',
  open: 'bg-accent',
  locked: 'bg-line',
};

/**
 * The plan's progress (UI-1): "Step N of M", then every step in order with its state.
 * An ordered list; the open step has aria-current="step". The count is a polite live
 * region, so a change of entry is announced ("Step 1 of 5").
 */
export function StepProgress({ session, actions }: { session: Session; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2">
        <p aria-live="polite" className="font-bold" data-testid="progress-count">
          {progressText(session)}
          {session.open_step && (
            <span className="font-normal text-ink-muted"> · {STEP_NAMES[session.open_step]}</span>
          )}
        </p>
        {actions}
      </div>
      <ol aria-label="Plan steps" className="grid auto-cols-fr grid-flow-col gap-1 sm:gap-2">
        {session.steps.map((state) => (
          <StepItem key={state.step} state={state} />
        ))}
      </ol>
    </div>
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
      <span aria-hidden="true" className={`h-1.5 rounded-full ${BAR[state.status]}`} />
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
